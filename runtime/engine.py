"""Five-Agent Department Supervised Runtime Engine (Phase 5.2 - Live LLM Execution).

Orchestrates the frozen Five-Agent Brain (CMO, Intelligence, Strategist, Creative, Performance)
with live UniversalModelGateway execution, ToolGateway execution, Knowledge retrieval,
Memory scoping, durable checkpointing, and Human Approval gating.
Permanent Logical Agent Count = 5. Zero Agent 6.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from governance.access_matrix import AgentAccessMatrix
from governance.claim_safety import FinalClaimAuditGateResult, ValidationDecision
from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from knowledge.models import KnowledgeCitation
from knowledge.repository import KnowledgeRepository, LocalKnowledgeRepository
from memory.learning import LearningEvent, LearningRepository, LocalLearningRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository, MemoryRepository
from chat.knowledge import SessionKnowledgeStore
from chat.router import fold_vietnamese
from runtime.artifacts import DepartmentRunArtifact, MemoryWriteCandidate
from runtime.context import (
    ApprovalState,
    EpistemicTier,
    EvidenceItem,
    ExecutionCheckpoint,
    GroundedContextPackage,
    RuntimeContext,
    RuntimeStage,
    RuntimeStatus,
)
from runtime.context_compiler import ContextCompiler
from runtime.handoff import (
    HANDOFF_PROMPT_INSTRUCTION,
    build_creative_spec,
    build_performance_evaluation,
    build_stage_handoff,
    extract_handoff_payload,
    render_handoff_sections,
)
from runtime.knowledge_builder import KnowledgeContextBuilder
from runtime.lineage import LineageInspector
from runtime.memory_builder import MemoryContextBuilder
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest

logger = logging.getLogger("department_runtime")


# ---------------------------------------------------------------------------
# Structural Constraint / Restriction Channel (COLLAB-03).
#
# A user/business/brand restriction must stay structurally available to every
# downstream stage instead of surviving only inside previous-agent prose.
# Strict data separation:
#   A. USER/SYSTEM restriction      -> rendered as BINDING CONSTRAINTS
#   B. Verified business/brand rule -> rendered as BINDING CONSTRAINTS (tagged)
#   C. Model suggestion             -> ledger ONLY, never promoted to binding
# ---------------------------------------------------------------------------

CONSTRAINT_ORIGINS = (
    "USER_CONSTRAINT",
    "BUSINESS_CONSTRAINT",
    "BRAND_CONSTRAINT",
    "POLICY_CONSTRAINT",
    "MODEL_RECOMMENDATION",
)

# Explicit imperative restriction phrasing only (small, principled set).
_IMPERATIVE_RESTRICTION_MARKERS = (
    # Vietnamese
    "không được", "không được phép", "đừng", "không tự động", "chỉ nhắm",
    "chỉ target", "chỉ dùng", "chỉ sử dụng", "tránh", "phải ở dưới",
    "phải dưới", "bắt buộc", "hạn chế",
    # English
    "do not ", "don't ", "must not ", "never ", "avoid ", "only target ",
    "only use ", "restrict ", "stay below ", "not exceed ",
)

_MAX_EXTRACTED_CONSTRAINTS = 10

# ---------------------------------------------------------------------------
# Value-origin contract (COLLAB-04): every structured stage-output field must
# truthfully declare where its value came from.
#   AGENT_DERIVED          - taken verbatim from actual model output
#   DETERMINISTIC_COMPUTED - computed from validated inputs by this runtime
#   TEMPLATE_UNVALIDATED   - static scaffolding (must never ship as conclusion)
#   NOT_PROVIDED           - the agent did not produce this; field stays empty
# A NOT_PROVIDED / empty value ALWAYS outranks a fabricated one.
# ---------------------------------------------------------------------------
VALUE_ORIGINS = (
    "AGENT_DERIVED",
    "DETERMINISTIC_COMPUTED",
    "TEMPLATE_UNVALIDATED",
    "NOT_PROVIDED",
)

# System bookkeeping confidence for CANDIDATE-tier run records.
# Semantics: 'unassessed bookkeeping entry' — NOT model certainty and NOT
# evidence strength. Deliberately below the 0.60 memory-verification
# threshold so such records can never auto-justify promotion.
CANDIDATE_BOOKKEEPING_CONFIDENCE = 0.5

_BINDING_CONSTRAINTS_HEADER = (
    "=== BINDING CONSTRAINTS & RESTRICTIONS (MUST OBEY — NOT EVIDENCE, NOT SUGGESTIONS) ==="
)

_UNRESOLVED_QUESTIONS_HEADER = "=== OPEN UNRESOLVED QUESTIONS (DO NOT INVENT ANSWERS) ==="

_PUBLISH_PROHIBITION_MARKERS = ("publish", "đăng bài", "đăng nội dung", "auto-publish")

_FORBIDDEN_AUTO_PUBLISH_PHRASES = (
    "auto-publish", "automatic publishing", "publish immediately",
    "tự động đăng", "đăng tự động", "đăng ngay lập tức",
)


def extract_explicit_user_constraints(raw_text: str) -> List[str]:
    """Deterministically extract EXPLICIT imperative restrictions from raw text.

    Only sentences phrased as explicit prohibitions/limits are returned, taken
    VERBATIM (no rewriting, no inference, no domain keywords). Matching is
    Vietnamese-accent-insensitive (folding used for DETECTION only; the
    original sentence is preserved verbatim). Fail-safe: returns [] on any
    malformed input. Model suggestions can never be created here because this
    reads only the user's raw request.
    """
    try:
        if not raw_text or not isinstance(raw_text, str):
            return []
        folded_markers = tuple(fold_vietnamese(m).lower() for m in _IMPERATIVE_RESTRICTION_MARKERS)
        found: List[str] = []
        seen = set()
        for sentence in re.split(r"(?<=[.!?\n])\s+", raw_text):
            candidate = sentence.strip()
            if not candidate or len(candidate) < 4:
                continue
            lowered = fold_vietnamese(candidate).lower()
            if any(marker in lowered for marker in folded_markers):
                key = lowered
                if key not in seen:
                    seen.add(key)
                    found.append(candidate)
            if len(found) >= _MAX_EXTRACTED_CONSTRAINTS:
                break
        return found
    except Exception:
        return []


def record_constraint(
    context: RuntimeContext,
    text: str,
    origin: str = "USER_CONSTRAINT",
    source: str = "user_request",
) -> bool:
    """Record a constraint with explicit origin typing.

    MODEL_RECOMMENDATION entries are stored in the audit ledger ONLY — they
    are never silently promoted into binding RuntimeContext.constraints.
    """
    if origin not in CONSTRAINT_ORIGINS:
        return False
    clean = (text or "").strip()
    if not clean:
        return False
    ledger = context.working_state.setdefault("constraint_ledger", [])
    ledger.append({"text": clean, "origin": origin, "source": source})
    if origin != "MODEL_RECOMMENDATION" and clean not in context.constraints:
        context.constraints.append(clean)
    return True


class FiveAgentDepartmentRuntime:
    """Supervised execution runtime for the Five-Agent Department."""

    def __init__(
        self,
        model_gateway: Optional[UniversalModelGateway] = None,
        tool_gateway: Optional[ToolGateway] = None,
        knowledge_repo: Optional[KnowledgeRepository] = None,
        memory_repo: Optional[MemoryRepository] = None,
        learning_repo: Optional[LearningRepository] = None,
        session_knowledge: Optional[SessionKnowledgeStore] = None,
        context_compiler: Optional[ContextCompiler] = None,
    ) -> None:
        self.model_gateway = model_gateway or UniversalModelGateway(free_only_mode=True)
        self.tool_gateway = tool_gateway or ToolGateway()
        self.knowledge_repo = knowledge_repo or LocalKnowledgeRepository()
        self.memory_repo = memory_repo or LocalMemoryRepository()
        self.learning_repo = learning_repo or LocalLearningRepository()
        self.session_knowledge = session_knowledge or SessionKnowledgeStore()

        self.knowledge_builder = KnowledgeContextBuilder(self.knowledge_repo)
        self.memory_builder = MemoryContextBuilder(self.memory_repo)
        self.context_compiler = context_compiler or ContextCompiler(
            session_knowledge=self.session_knowledge,
            knowledge_repo=self.knowledge_repo,
            memory_repo=self.memory_repo,
        )
        self.lineage_inspector = LineageInspector()

        self._active_contexts: Dict[str, RuntimeContext] = {}
        self._completed_runs: Dict[str, DepartmentRunArtifact] = {}
        self._executed_tool_idempotency_keys: Dict[str, ExecutionReceipt] = {}

    def _call_agent_llm(
        self,
        agent_name: str,
        system_instruction: str,
        user_prompt: str,
        temperature: float = 0.3,
        timeout_seconds: Optional[float] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """Helper to invoke UniversalModelGateway for an agent stage.

        Returns (content, error_detail). If successful, error_detail is None.
        """
        if not self.model_gateway:
            return None, "NO_MODEL_GATEWAY"

        # COLLAB-05: every stage may append the optional machine handoff block
        # to the SAME single response (no second agent, no second model call).
        system_instruction = system_instruction + HANDOFF_PROMPT_INSTRUCTION

        req = ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content=system_instruction),
                ModelMessage(role=ModelRole.USER, content=user_prompt),
            ],
            temperature=temperature,
            max_tokens=4096,
            timeout_seconds=timeout_seconds,
        )
        try:
            resp = self.model_gateway.generate(req)
            if resp.status == ModelResponseStatus.SUCCESS and resp.content:
                return resp.content.strip(), None
            err = resp.error or f"MODEL_RESPONSE_{resp.status.value}"
            logger.warning(f"Agent {agent_name} LLM call failed: {err}")
            return None, err
        except Exception as e:
            logger.warning(f"Agent {agent_name} LLM call exception: {e}")
            return None, str(e)

    def start_run(
        self,
        objective: str,
        business_id: str = "BIZ_001",
        campaign_id: str = "CAMP_001",
        user_id: str = "USER_001",
        run_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> RuntimeContext:
        """Initialize a new supervised department run."""
        rid = run_id or f"RUN-DEPT-{uuid.uuid4().hex[:8].upper()}"
        context = RuntimeContext(
            run_id=rid,
            objective=objective,
            business_id=business_id,
            campaign_id=campaign_id,
            user_id=user_id,
            chat_id=chat_id,
            project_id=project_id,
            status=RuntimeStatus.RUNNING,
            current_stage=RuntimeStage.INIT,
        )
        # COLLAB-03: structurally capture explicit user restrictions from the
        # raw objective (verbatim; deterministic; fail-closed to empty).
        for extracted in extract_explicit_user_constraints(objective):
            record_constraint(context, extracted, origin="USER_CONSTRAINT", source="raw_user_objective")
        self._sync_constraint_state(context)
        self._active_contexts[rid] = context
        context.create_checkpoint()
        return context

    def execute_stage_cmo_initial(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 1: Initial CMO Strategic Framing and Task Decomposition."""
        context.current_stage = RuntimeStage.CMO_INITIAL
        k_res = self.knowledge_builder.build_context_for_agent("cmo", query_text=context.objective)
        m_res = self.memory_builder.build_context_for_agent("cmo", query_text=context.objective)

        for c in k_res.citations:
            context.knowledge_refs.append(c.citation_id)
            self.lineage_inspector.add_citation(c)
        for m in m_res.memories:
            context.memory_refs.append(m.memory_id)

        # Grounded Context Compilation
        grounded_pkg = self.context_compiler.compile_grounded_package("cmo", context)
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        # Dynamic LLM Strategic Framing
        sys_prompt = (
            "You are the Chief Marketing Officer (CMO) and Executive Master Orchestrator of the Five-Agent AI Marketing Department.\n"
            "Decompose the user's commercial marketing objective into clear, structured delegation directives for:\n"
            "- Intelligence: Competitor & market research focus\n"
            "- Strategist: Value proposition & audience positioning\n"
            "- Creative: High-converting hooks & multimedia concept directions\n"
            "- Performance: KPI tree, attribution model & budget allocation\n"
            "Mirror the language of the user objective (Vietnamese/English)."
        )
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Marketing Objective: {context.objective}\nWorkspace/Brand: {context.business_id}\n\n{evidence_section}".strip()
        user_prompt = self._append_governance_block(context, user_prompt)
        llm_output, err = self._call_agent_llm("cmo", sys_prompt, user_prompt)

        if not llm_output:
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"CMO_INITIAL_FAILED: {err}")
            output = {
                "stage": "CMO_INITIAL",
                "agent": "cmo",
                "status": "FAILED",
                "error": err or "MODEL_PROVIDER_FAILURE",
                "strategic_intent": "",
                "delegation_plan": {},
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["cmo_initial"] = output
            context.create_checkpoint()
            return output

        output = {
            "stage": "CMO_INITIAL",
            "agent": "cmo",
            "status": "COMPLETED",
            "strategic_intent": llm_output,
            "delegation_plan": {
                # COLLAB-05: directives reference the objective without
                # re-quoting it (single-occurrence contract in prompts).
                "intelligence_focus": "Investigate market landscape, customer pain points, and competitors for the stated objective",
                "strategist_focus": "Define ICP segments, value proposition, and positioning hierarchy for the stated objective",
                "creative_focus": "Develop creative angles, high-converting hooks, and ad copy for the stated objective",
                "performance_focus": "Establish CAC/ROAS targets, channel mix, and experiment roadmap for the stated objective",
            },
            "citations": [c.citation_id for c in k_res.citations],
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(
            context, "cmo_initial", "cmo", llm_output, output, delegation=output.get("delegation_plan"),
        )
        context.stage_outputs["cmo_initial"] = output
        context.create_checkpoint()
        return output

    def execute_stage_intelligence(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 2: Intelligence Research & Sensory Tool Invocation."""
        context.current_stage = RuntimeStage.INTELLIGENCE

        k_res = self.knowledge_builder.build_context_for_agent("intelligence", query_text=context.objective)
        for c in k_res.citations:
            context.knowledge_refs.append(c.citation_id)
            self.lineage_inspector.add_citation(c)

        # Invoke ToolGateway for search observation
        idem_key = f"{context.run_id}:intelligence:web_search:{context.objective}"
        if idem_key in self._executed_tool_idempotency_keys:
            search_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            search_req = ToolRequest(
                run_id=context.run_id,
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": context.objective},
            )
            search_receipt = self.tool_gateway.execute(search_req)
            self._executed_tool_idempotency_keys[idem_key] = search_receipt

        context.execution_receipt_refs.append(search_receipt.execution_id)
        self.lineage_inspector.add_receipt(search_receipt)

        # Grounded Context Compilation with actual Tool Receipt content
        grounded_pkg = self.context_compiler.compile_grounded_package("intelligence", context, tool_receipts=[search_receipt])
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            output = {
                "stage": "INTELLIGENCE",
                "agent": "intelligence",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "market_findings": "",
                "search_receipt_id": search_receipt.execution_id,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["intelligence"] = output
            context.create_checkpoint()
            return output

        # Dynamic LLM Intelligence Analysis
        sys_prompt = (
            "You are the Intelligence Specialist in the Five-Agent AI Marketing Department.\n"
            "Conduct thorough market, competitor, and customer research based on the CMO directive.\n"
            "Identify key market trends, customer motivations, objections, and competitor benchmarks.\n"
            "Mirror the language of the user objective."
        )
        cmo_intent = context.stage_outputs.get("cmo_initial", {}).get("strategic_intent", context.objective)
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Objective: {context.objective}\nCMO Directive: {cmo_intent}\n\n{evidence_section}".strip()
        user_prompt = self._append_governance_block(context, user_prompt)
        llm_findings, err = self._call_agent_llm("intelligence", sys_prompt, user_prompt)

        if not llm_findings:
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"INTELLIGENCE_FAILED: {err}")
            output = {
                "stage": "INTELLIGENCE",
                "agent": "intelligence",
                "status": "FAILED",
                "error": err or "MODEL_PROVIDER_FAILURE",
                "market_findings": "",
                "search_receipt_id": search_receipt.execution_id,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["intelligence"] = output
            context.create_checkpoint()
            return output

        output = {
            "stage": "INTELLIGENCE",
            "agent": "intelligence",
            "status": "COMPLETED",
            "market_findings": llm_findings,
            "search_receipt_id": search_receipt.execution_id,
            "citations": [c.citation_id for c in k_res.citations],
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(context, "intelligence", "intelligence", llm_findings, output)
        context.stage_outputs["intelligence"] = output
        context.create_checkpoint()
        return output

    def execute_stage_strategist(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 3: Strategist Positioning & Value Architecture."""
        context.current_stage = RuntimeStage.STRATEGIST
        k_res = self.knowledge_builder.build_context_for_agent("strategist", query_text=context.objective)
        m_res = self.memory_builder.build_context_for_agent("strategist", query_text=context.objective)

        for c in k_res.citations:
            context.knowledge_refs.append(c.citation_id)
            self.lineage_inspector.add_citation(c)
        for m in m_res.memories:
            context.memory_refs.append(m.memory_id)

        # Grounded Context Compilation
        grounded_pkg = self.context_compiler.compile_grounded_package("strategist", context)
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("intelligence", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            output = {
                "stage": "STRATEGIST",
                "agent": "strategist",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "positioning": "",
                "target_segments": [],
                "value_propositions": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["strategist"] = output
            context.create_checkpoint()
            return output

        # Dynamic LLM Strategy
        sys_prompt = (
            "You are the Marketing Strategist in the Five-Agent AI Marketing Department.\n"
            "Synthesize the market intelligence into a sharp positioning architecture, defining:\n"
            "1. Primary Ideal Customer Profile (ICP) & Beachhead Segments\n"
            "2. Core Value Proposition & Category Point-of-View\n"
            "3. Messaging Hierarchy & Proof Pillars\n"
            "Mirror the language of the user objective."
        )
        intel_findings = context.stage_outputs.get("intelligence", {}).get("market_findings", "")
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Objective: {context.objective}\nIntelligence Research: {intel_findings}\n\n{evidence_section}".strip()
        user_prompt = self._append_governance_block(context, user_prompt)
        llm_strategy, err = self._call_agent_llm("strategist", sys_prompt, user_prompt)

        if not llm_strategy:
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"STRATEGIST_FAILED: {err}")
            output = {
                "stage": "STRATEGIST",
                "agent": "strategist",
                "status": "FAILED",
                "error": err or "MODEL_PROVIDER_FAILURE",
                "positioning": "",
                "target_segments": [],
                "value_propositions": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["strategist"] = output
            context.create_checkpoint()
            return output

        output = {
            "stage": "STRATEGIST",
            "agent": "strategist",
            "status": "COMPLETED",
            "positioning": llm_strategy,
            # COLLAB-04: no structured segment/proposition parser contract
            # exists; fields stay honestly empty instead of fabricated.
            "target_segments": [],
            "value_propositions": [],
            "field_origins": {
                "positioning": "AGENT_DERIVED",
                "target_segments": "NOT_PROVIDED",
                "value_propositions": "NOT_PROVIDED",
            },
            "citations": [c.citation_id for c in k_res.citations],
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(context, "strategist", "strategist", llm_strategy, output)
        context.stage_outputs["strategist"] = output
        context.create_checkpoint()
        return output

    def execute_stage_creative(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 4: Creative Generation & Asset Synthesis."""
        context.current_stage = RuntimeStage.CREATIVE
        k_res = self.knowledge_builder.build_context_for_agent("creative", query_text=context.objective)
        for c in k_res.citations:
            context.knowledge_refs.append(c.citation_id)
            self.lineage_inspector.add_citation(c)

        # Invoke ToolGateway for local image generation / asset preparation
        idem_key = f"{context.run_id}:creative:image_generation:hero"
        if idem_key in self._executed_tool_idempotency_keys:
            img_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            img_req = ToolRequest(
                run_id=context.run_id,
                agent_id="creative",
                capability_id="image_generation",
                parameters={"prompt": f"Hero marketing visual concept for {context.objective}"},
            )
            img_receipt = self.tool_gateway.execute(img_req)
            self._executed_tool_idempotency_keys[idem_key] = img_receipt

        context.execution_receipt_refs.append(img_receipt.execution_id)
        self.lineage_inspector.add_receipt(img_receipt)
        if img_receipt.artifact_references:
            context.artifact_refs.extend(img_receipt.artifact_references)

        # Grounded Context Compilation with image tool receipt
        grounded_pkg = self.context_compiler.compile_grounded_package("creative", context, tool_receipts=[img_receipt])
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("strategist", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            output = {
                "stage": "CREATIVE",
                "agent": "creative",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "concept_name": "",
                "visual_asset_receipt": img_receipt.execution_id,
                "creative_synthesis": "",
                "copy_headlines": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["creative"] = output
            context.create_checkpoint()
            return output

        # Dynamic LLM Creative Synthesis
        sys_prompt = (
            "You are the Creative Director and Copywriter in the Five-Agent AI Marketing Department.\n"
            "Develop 3-5 high-converting ad angles with scroll-stopping hooks, ad copy, and short-form video scripts (Meta, TikTok, YouTube Shorts).\n"
            "Mirror the language of the user objective."
        )
        strat_pos = context.stage_outputs.get("strategist", {}).get("positioning", "")
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Objective: {context.objective}\nPositioning Strategy: {strat_pos}\n\n{evidence_section}".strip()
        user_prompt = self._append_governance_block(context, user_prompt)
        llm_creative, err = self._call_agent_llm("creative", sys_prompt, user_prompt, temperature=0.7)

        if not llm_creative:
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"CREATIVE_FAILED: {err}")
            output = {
                "stage": "CREATIVE",
                "agent": "creative",
                "status": "FAILED",
                "error": err or "MODEL_PROVIDER_FAILURE",
                "concept_name": "",
                "visual_asset_receipt": img_receipt.execution_id,
                "creative_synthesis": "",
                "copy_headlines": [],
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["creative"] = output
            context.create_checkpoint()
            return output

        output = {
            "stage": "CREATIVE",
            "agent": "creative",
            "status": "COMPLETED",
            # COLLAB-04: creative_synthesis is the authoritative artifact.
            # concept_name/headlines stay absent unless actually produced.
            "concept_name": None,
            "visual_asset_receipt": img_receipt.execution_id,
            "creative_synthesis": llm_creative,
            "copy_headlines": [],
            "field_origins": {
                "creative_synthesis": "AGENT_DERIVED",
                "concept_name": "NOT_PROVIDED",
                "copy_headlines": "NOT_PROVIDED",
            },
            "citations": [c.citation_id for c in k_res.citations],
        }
        # COLLAB-06: expose the real asset receipt to the CreativeSpec builder.
        output["_img_receipt_dump"] = {
            "execution_id": img_receipt.execution_id,
            "capability_id": img_receipt.capability_id,
            "status": img_receipt.status.value,
            "execution_mode": img_receipt.execution_mode.value,
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(context, "creative", "creative", llm_creative, output)
        context.stage_outputs["creative"] = output
        context.create_checkpoint()
        return output

    def execute_stage_performance(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 5: Performance Analytics, Attribution & Experiment Portfolio."""
        context.current_stage = RuntimeStage.PERFORMANCE
        k_res = self.knowledge_builder.build_context_for_agent("performance", query_text=context.objective)
        m_res = self.memory_builder.build_context_for_agent("performance", query_text=context.objective)

        for c in k_res.citations:
            context.knowledge_refs.append(c.citation_id)
            self.lineage_inspector.add_citation(c)
        for m in m_res.memories:
            context.memory_refs.append(m.memory_id)

        # Invoke ToolGateway for analytics calculation
        idem_key = f"{context.run_id}:performance:kpi_calculation:cac"
        if idem_key in self._executed_tool_idempotency_keys:
            calc_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            calc_req = ToolRequest(
                run_id=context.run_id,
                agent_id="performance",
                capability_id="kpi_calculation",
                parameters={"metric_name": "target_cac", "target_value": 150.0},
            )
            calc_receipt = self.tool_gateway.execute(calc_req)
            self._executed_tool_idempotency_keys[idem_key] = calc_receipt

        context.execution_receipt_refs.append(calc_receipt.execution_id)
        self.lineage_inspector.add_receipt(calc_receipt)

        # Grounded Context Compilation with KPI calc tool receipt
        grounded_pkg = self.context_compiler.compile_grounded_package("performance", context, tool_receipts=[calc_receipt])
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("creative", {}).get("status") == "FAILED":
            context.status = RuntimeStatus.FAILED
            output = {
                "stage": "PERFORMANCE",
                "agent": "performance",
                "status": "FAILED",
                "error": "PREVIOUS_STAGE_FAILED",
                "funnel_kpi": "",
                "experiment_blueprint": {},
                "calc_receipt_id": calc_receipt.execution_id,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["performance"] = output
            context.create_checkpoint()
            return output

        # Dynamic LLM Performance Modeling
        sys_prompt = (
            "You are the Performance Marketing & Analytics Director in the Five-Agent AI Marketing Department.\n"
            "Build an attribution framework, media allocation model, KPI tree, and structured A/B experiment backlog for this campaign.\n"
            "Mirror the language of the user objective."
        )
        strat_pos = context.stage_outputs.get("strategist", {}).get("positioning", "")
        # COLLAB-06: Performance evaluates the ACTUAL creative work, not a
        # synthetic/absent concept_name.
        creative_synthesis = context.stage_outputs.get("creative", {}).get("creative_synthesis", "") or ""
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = (
            f"Objective: {context.objective}\n"
            f"Strategy: {strat_pos}\n"
            f"Creative Synthesis (authoritative, from Creative this run): {creative_synthesis}\n\n"
            f"{evidence_section}"
        ).strip()
        user_prompt = self._append_governance_block(context, user_prompt)
        llm_perf, err = self._call_agent_llm("performance", sys_prompt, user_prompt)

        if not llm_perf:
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"PERFORMANCE_FAILED: {err}")
            output = {
                "stage": "PERFORMANCE",
                "agent": "performance",
                "status": "FAILED",
                "error": err or "MODEL_PROVIDER_FAILURE",
                "funnel_kpi": "",
                "experiment_blueprint": {},
                "calc_receipt_id": calc_receipt.execution_id,
                "citations": [c.citation_id for c in k_res.citations],
            }
            context.stage_outputs["performance"] = output
            context.create_checkpoint()
            return output

        output = {
            "stage": "PERFORMANCE",
            "agent": "performance",
            "status": "COMPLETED",
            "funnel_kpi": llm_perf,
            # COLLAB-04: no structured experiment was actually produced;
            # blueprint stays empty instead of an invented hypothesis/metric.
            "experiment_blueprint": {},
            "calc_receipt_id": calc_receipt.execution_id,
            "field_origins": {
                "funnel_kpi": "AGENT_DERIVED",
                "experiment_blueprint": "NOT_PROVIDED",
            },
            "citations": [c.citation_id for c in k_res.citations],
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(context, "performance", "performance", llm_perf, output)
        context.stage_outputs["performance"] = output
        context.create_checkpoint()
        return output

    # ------------------------------------------------------------------
    # Final CMO fail-closed authorization policy (COLLAB-02).
    #
    # Deterministic infrastructure gate reusing the repository's existing
    # claim-safety vocabulary (FinalClaimAuditGateResult /
    # APPROVED | APPROVED_WITH_CONDITIONS | BLOCKED). This is POLICY, not a
    # sixth agent: it never calls a model and never generates content.
    # The LLM is not the authorization authority.
    # ------------------------------------------------------------------

    _FACTUAL_CLAIM_PATTERNS = (
        # 1. Quantified / Multipliers / Metrics / Percentages / Population counts
        re.compile(r"\b(?:\d+(?:\.\d+)?\s*[xX]|\d+(?:\.\d+)?\s*(?:times?|fold))\s+(?:longer|faster|better|more|higher|cheaper|smaller|quieter|durable|lasting)\b", re.IGNORECASE),
        re.compile(r"\b(?:gấp|gap)\s+\d+(?:\.\d+)?\s*(?:lần|lan)\b", re.IGNORECASE),
        re.compile(r"\b(?:twice|3x|4x|5x|10x)\s+(?:as\s+\w+|more|faster|longer|better|greater)\b", re.IGNORECASE),
        re.compile(r"\b(?:save|tiết\s+kiệm|tiet\s+kiem|giảm|giam|discount|off)\s+\d{1,3}\s*%", re.IGNORECASE),
        re.compile(r"\b\d{1,3}\s*%\s*(?:savings?|tiết\s+kiệm|tiet\s+kiem|off|discount|giảm|giam)", re.IGNORECASE),
        re.compile(r"\b(?:reduce|cắt\s+giảm|cat\s+giam|tăng|tang|increase|boost|improve|cải\s+thiện|cai\s+thien)\s+(?:cpa|cac|cpc|conversion|ctr|cvr|roas|cost|chi\s+phí|chi\s+phi|sales|revenue|doanh\s+thu|bounce\s+rate|churn)\s+(?:by\s+)?\d{1,3}\s*%", re.IGNORECASE),
        re.compile(r"\b\d+\s*(?:out\s+of|\/)\s*\d+\s*(?:users?|customers?|people|consumers?|khách\s+hàng|khach\s+hang|người\s+dùng|nguoi\s+dung)\b", re.IGNORECASE),
        re.compile(r"\b\d{1,3}\s*%\s*(?:of\s+(?:users?|customers?|people|consumers?|businesses?|mothers?|dermatologists?)|của\s+(?:khách\s+hàng|khach\s+hang|người\s+dùng|nguoi\s+dung))", re.IGNORECASE),
        re.compile(r"\b\d+(?:[,\.]\d+)?\s*(?:million|triệu|trieu|thousand|nghìn|nghin|k|K)\s+(?:units?|devices?|users?|customers?|downloads?|businesses?|sản\s+phẩm|san\s+pham|khách\s+hàng|khach\s+hang|doanh\s+nghiệp|doanh\s+nghiep)\s*(?:sold|active|using|trusted|đã\s+bán|da\s+ban|tin\s+dùng|tin\s+dung|sử\s+dụng|su\s+dung)?\b", re.IGNORECASE),
        re.compile(r"\b(?:used\s+by|tin\s+dùng\s+bởi|trusted\s+by)\s+\d+(?:,\d{3})+\b", re.IGNORECASE),

        # 2. Ranking & Superlatives
        re.compile(r"(?:(?<!\w)#\s*\d+|\b(?:no\.?\s*\d+|số\s*\d+|so\s*\d+|top\s*\d+)\b)", re.IGNORECASE),
        re.compile(r"\b(?:rated|ranked|xếp\s+hạng|danh\s+gia)\s+(?:#\s*1|no\.?\s*1|số\s*1|so\s*1|top\s*\d+)\b", re.IGNORECASE),
        re.compile(r"\b(?:best[-\s]?selling|bán\s+chạy\s+nhất|ban\s+chay\s+nhat|fastest\s+charger|sạc\s+nhanh\s+nhất|sac\s+nhanh\s+nhat|most\s+trusted|được\s+tin\s+dùng\s+nhất|duoc\s+tin\s+dung\s+nhat|market\s+leader|dẫn\s+đầu\s+thị\s+trường|dan\s+dau\s+thi\s+truong|highest\s+rated|được\s+đánh\s+giá\s+cao\s+nhất)\b", re.IGNORECASE),

        # 3. Comparative facts
        re.compile(r"\b(?:lasts?|durable|faster|better|cheaper|quieter|more\s+durable)\s+than\s+(?:every|all|any|our|the)?\s*competitors?\b", re.IGNORECASE),
        re.compile(r"\b(?:không\s+đối\s+thủ\s+nào|khong\s+doi\s+thu\s+nao|no\s+competitor)\s+(?:bền\s+bằng|ben\s+bang|sánh\s+bằng|bằng|matches|beats|exceeds|is\s+more)\b", re.IGNORECASE),
        re.compile(r"\b(?:twice|3x|5x)\s+as\s+\w+\s+as\s+(?:model\s+\w+|competitor|iphone|samsung)\b", re.IGNORECASE),

        # 4. Material / Hardware Specs
        re.compile(r"\b(?:aerospace[-\s]?grade\s+titanium|hợp\s+kim\s+titan\s+hàng\s+không|khung\s+titan\s+hàng\s+không|khung\s+titan\s+hang\s+khong|grade\s+5\s+titanium)\b", re.IGNORECASE),
        re.compile(r"\b(?:IP6[78]|IP\d{2})\s*(?:certified|compliant|waterproof|chuẩn|chứng\s+nhận|đạt\s+chuẩn|dat\s+chuan)\b", re.IGNORECASE),
        re.compile(r"\b\d{3,5}\s*mAh\s*(?:battery|pin)?\b", re.IGNORECASE),
        re.compile(r"\b(?:supports?|hỗ\s+trợ|ho\s+tro)\s+\d{2,3}\s*W\s*(?:pd\s+charging|fast\s+charging|sạc\s+nhanh|sac\s+nhanh)\b", re.IGNORECASE),

        # 5. Certification / Clinical Authority
        re.compile(r"\b(?:clinically\s+(?:proven|tested|validated)|chứng\s+minh\s+lâm\s+sàng|chung\s+minh\s+lam\s+sang|được\s+chứng\s+minh|duoc\s+chung\s+minh|proven\s+results)\b", re.IGNORECASE),
        re.compile(r"\b(?:dermatologist\s+(?:tested|approved|recommended)|bác\s+sĩ\s+da\s+liễu\s+(?:khuyên\s+dùng|chứng\s+nhận)|recommended\s+by\s+dermatologists?)\b", re.IGNORECASE),
        re.compile(r"\b(?:FDA|USDA\s+Organic|CE|ISO\s*\d+)\s*(?:approved|certified|chứng\s+nhận|đạt\s+chuẩn|dat\s+chuan)\b", re.IGNORECASE),

        # 6. Price / Savings / Guarantees
        re.compile(r"\b(?:money[-\s]?back\s+guarantee|cam\s+kết\s+hoàn\s+tiền|cam\s+ket\s+hoan\s+tien|hoàn\s+tiền\s+100%\s+trong\s+\d+\s*ngày|hoan\s+tien\s+100%\s+trong\s+\d+\s*ngay|30[-\s]?day\s+money[-\s]?back)\b", re.IGNORECASE),
        re.compile(r"\b(?:bảo\s+hành|bao\s+hanh|warranty)\s*(?:chính\s+hãng|trọn\s+đời|lifetime|\d+\s*(?:tháng|thang|năm|nam|ngày|ngay|months?|years?))\b", re.IGNORECASE),
        re.compile(r"\b(?:lifetime\s+warranty|24[-\s]?month\s+warranty|12[-\s]?month\s+warranty)\b", re.IGNORECASE),
        re.compile(r"\b(?:only|chỉ\s+với|chi\s+voi)\s*(?:\$\s*\d+|\d+\s*USD|\d+\s*(?:triệu|tr|k|K|đ|VND))\b", re.IGNORECASE),

        # 7. Market Statistics
        re.compile(r"\b\d+\s*%\s*(?:of\s+customers|of\s+users|khách\s+hàng|người\s+dùng)\s+(?:prefer|choose|tin\s+dùng|lựa\s+chọn)\b", re.IGNORECASE),
    )

    _HYPOTHESIS_MARKERS = (
        "hypothesis", "giả thuyết", "gia thuyet", "concept", "ý tưởng", "y tuong",
        "idea", "suggestion", "đề xuất", "de xuat", "placeholder", "to be tested",
        "cần kiểm chứng", "can kiem chung", "unverified", "chưa xác minh", "chua xac minh",
        "mock", "simulated", "creative direction", "not a factual claim",
        "we hypothesize", "hypothesize that", "propose testing", "we should test",
        "cần thử nghiệm", "can thu nghiem", "might improve", "may improve",
    )

    _PLANNING_MARKERS = (
        "target", "mục tiêu", "muc tieu", "goal", "aims to", "aim to",
        "plan to", "kế hoạch", "ke hoach", "dự kiến", "du kien",
        "propose", "proposing", "expected savings may reach", "may reach",
        "might reach", "if we", "whether", "would consider", "planning",
    )

    _SOURCE_CITATION_PATTERN = re.compile(
        r"(?:source|nguồn|evidence|receipt)\s*[:#=]?\s*([A-Za-z][A-Za-z0-9\-_]+)",
        re.IGNORECASE,
    )

    _INCONCLUSIVE_MARKERS = (
        "inconclusive", "không thể kết luận", "không kết luận", "insufficient evidence",
        "dữ liệu không đủ", "chưa đủ dữ liệu", "no winner", "no causal conclusion",
        "undetermined",
    )

    _PLANNING_OR_CONDITIONAL_PERFORMANCE_PATTERN = re.compile(
        r"\b(?:target|threshold|ngưỡng|mục\s+tiêu|goal|if\b|whether|will\s+consider|means\s+|aims?\s+to|should\s+test|plan\s+to|propos|kế\s+hoạch|dự\s+kiến|to\s+be\s+tested)\b",
        re.IGNORECASE,
    )

    _OBSERVED_PERFORMANCE_RESULT_PATTERNS = (
        # Winner / victory assertions
        re.compile(r"\b(?:winners?|won|chiến\s+thắng|trúng\s+chiến\s+dịch)\b", re.IGNORECASE),
        # Experiment success / validation assertions
        re.compile(r"\b(?:experiment|test|thử\s+nghiệm)\s+(?:succeeded|validated|proved|thành\s+công)\b", re.IGNORECASE),
        re.compile(r"\b(?:validated|xác\s+thực|chứng\s+minh)\s+(?:the\s+hypothesis|giả\s+thuyết|variant\s+[a-z0-9]|biến\s+thể\s+[a-z0-9])\b", re.IGNORECASE),
        # Outperformance assertions
        re.compile(r"\b(?:outperformed|vượt\s+trội)\s+(?:control|đối\s+chứng)\b", re.IGNORECASE),
        # Measured post-test / pilot empirical statements
        re.compile(r"\b(?:after\s+the\s+test|post-test|measured\s+(?:conversion|ctr|cvr|metric|rate|result)|results?\s+from\s+the\s+(?:pilot|test|experiment)|sau\s+thử\s+nghiệm|kết\s+quả\s+(?:pilot|thử\s+nghiệm|đo\s+lường))\b", re.IGNORECASE),
        re.compile(r"\b(?:post-test\s+metric|measured\s+result|measured\s+rate|pilot\s+data)\s+(?:was|showed|shows|đạt|cho\s+thấy|materially)\b", re.IGNORECASE),
        # Observed metric / uplift assertions
        re.compile(r"\b(?:observed|ghi\s+nhận|đo\s+lường\s+được)\s+(?:[+\-]?\d+\s*%\s*(?:ctr|cvr|conversion|roas|cpc|cpa|lift|uplift)|(?:uplift|lift|increase|tăng\s+trưởng)\s+(?:was|đạt|là)?\s*[+\-]?\d+\s*%)\b", re.IGNORECASE),
        re.compile(r"\b(?:variant\s+[a-z0-9]|biến\s+thể\s+[a-z0-9]|campaign|chiến\s+dịch)\s+(?:outperformed|increased|improved|boosted|achieved|vượt\s+trội|tăng|đạt)\s+(?:control|đối\s+chứng|(?:ctr|cvr|conversion|roas|lift|uplift)\s+(?:by\s+)?[+\-]?\d+\s*%|[+\-]?\d+\s*%\s*(?:ctr|cvr|conversion|roas|lift|uplift)|(?:a\s+)?[+\-]?\d+\s*%\s*(?:conversion|ctr|cvr|lift|uplift))", re.IGNORECASE),
        re.compile(r"\b(?:ctr|cvr|conversion\s+rate|roas)\s+(?:improved|increased|rose|boosted|tăng|cải\s+thiện)\s+(?:from\s+\d+[%a-z0-9.]*\s+to\s+\d+[%a-z0-9.]*|by\s+[+\-]?\d+\s*%|[+\-]?\d+\s*%)", re.IGNORECASE),
        re.compile(r"\b[+\-]?\d+\s*%\s*(?:ctr|cvr|conversion)\s+(?:increase|lift|uplift|tăng\s+trưởng)\b", re.IGNORECASE),
        re.compile(r"\b(?:achieved|attained|đạt)\s+(?:a\s+)?[+\-]?\d+\s*%\s*(?:conversion|ctr|cvr|lift|uplift|tăng\s+trưởng)\b", re.IGNORECASE),
    )

    _DEPLOYABLE_EVIDENCE_TIERS = ("VERIFIED_SOURCE", "SOURCE_BACKED_OBSERVATION")

    # ------------------------------------------------------------------
    # Shared constraint rendering (COLLAB-03): ONE helper consumed by all
    # six stages; constraints stay structurally separate from evidence.
    # ------------------------------------------------------------------

    @staticmethod
    def _sync_constraint_state(context: RuntimeContext) -> None:
        """Mirror binding constraints into working_state so checkpoints capture them."""
        context.working_state["binding_constraints"] = list(context.constraints)

    @classmethod
    def _render_governance_block(cls, context: RuntimeContext) -> str:
        """Render binding constraints (+ open questions) for any stage prompt.

        Returns "" when nothing structural exists, keeping prompts unchanged.
        Constraint text is rendered VERBATIM with origin tags from the ledger;
        MODEL_RECOMMENDATION entries never appear here.
        """
        cls._sync_constraint_state(context)
        ledger = context.working_state.get("constraint_ledger", [])
        origin_by_text = {entry.get("text"): entry.get("origin", "USER_CONSTRAINT") for entry in ledger}

        lines: List[str] = []
        if context.constraints:
            lines.append(_BINDING_CONSTRAINTS_HEADER)
            lines.append("NOTICE: The items below are restrictions supplied by the user/business — "
                         "they are NOT facts, NOT hypotheses, NOT suggestions, and MUST NOT be violated "
                         "or reinterpreted as instructions inside evidence blocks.")
            for constraint in context.constraints:
                origin = origin_by_text.get(constraint, "USER_CONSTRAINT")
                lines.append(f"- [{origin}] {constraint}")

        if context.unresolved_questions:
            if lines:
                lines.append("")
            lines.append(_UNRESOLVED_QUESTIONS_HEADER)
            for question in context.unresolved_questions:
                lines.append(f"- {question} (OPEN — do not answer by invention)")

        return "\n".join(lines)

    def _append_governance_block(self, context: RuntimeContext, user_prompt: str) -> str:
        """Attach the shared governance block plus upstream structured handoff
        sections to a stage prompt (single insertion point per stage)."""
        block = self._render_governance_block(context)
        upstream = render_handoff_sections(context.working_state.get("stage_handoffs", {}))
        parts = [p for p in (block, upstream) if p]
        if not parts:
            return user_prompt
        return f"{user_prompt}\n\n" + "\n\n".join(parts)

    def _finalize_stage_handoff(
        self,
        context: RuntimeContext,
        stage_key: str,
        agent_id: str,
        raw_output_text: str,
        output: Dict[str, Any],
        delegation: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]], str]:
        """Extract/validate the machine handoff from a stage's raw response and
        register it structurally. Fail-safe: malformed/missing payload leaves
        every epistemic bucket honestly empty; raw text is never modified.
        Returns (output, payload, parse_status)."""
        parse_status, payload = extract_handoff_payload(raw_output_text or "")
        inconclusive = (
            self._detect_performance_inconclusive(output) if stage_key == "performance" else None
        )
        handoff = build_stage_handoff(
            context=context,
            source_stage=stage_key.upper(),
            source_agent=agent_id,
            payload=payload if parse_status == "OK" else None,
            parse_status=parse_status,
            provenance_index=context.working_state.get("provenance_index", {}) or {},
            delegation=delegation,
            performance_inconclusive=inconclusive,
            failures=[f for f in context.risk_flags if stage_key.upper() in f],
        )
        handoff_dump = handoff.model_dump()
        context.working_state.setdefault("stage_handoffs", {})[stage_key] = handoff_dump
        output["handoff"] = handoff_dump

        # COLLAB-06: CreativeSpec for the creative stage (reuses validated
        # handoff items; optional machine fields only; nothing fabricated).
        if stage_key == "creative":
            spec_payload = payload.get("creative_spec") if isinstance(payload, dict) else None
            spec = build_creative_spec(
                context=context,
                handoff_dump=handoff_dump,
                spec_payload=spec_payload,
                asset_receipts=[{
                    "execution_id": r.get("execution_id", ""),
                    "capability_id": r.get("capability_id", ""),
                    "status": r.get("status", ""),
                    "execution_mode": r.get("execution_mode", ""),
                } for r in [output.get("_img_receipt_dump") or {}] if r],
            )
            spec_dump = spec.model_dump()
            handoff_dump["creative_spec"] = spec_dump
            output["creative_spec"] = spec_dump
            context.working_state["creative_spec"] = spec_dump
            output.pop("_img_receipt_dump", None)

        # COLLAB-06: deterministic Performance evaluation summary.
        if stage_key == "performance":
            evaluation_payload = payload.get("evaluation") if isinstance(payload, dict) else None
            creative_hypothesis_ids = [
                h.get("item_id", "")
                for h in (context.working_state.get("creative_spec", {}) or {}).get("hypotheses", [])
            ]
            evaluation = build_performance_evaluation(
                perf_handoff_dump=handoff_dump,
                evaluation_payload=evaluation_payload,
                provenance_index=context.working_state.get("provenance_index", {}) or {},
                valid_hypothesis_ids=creative_hypothesis_ids,
            )
            handoff_dump["evaluation_status"] = evaluation["evaluation_status"]
            handoff_dump["evaluation_data_origin"] = evaluation["data_origin"]
            handoff_dump["evaluation_hypothesis_ref"] = evaluation["hypothesis_ref"]
            handoff_dump["metric_refs"] = evaluation["metric_refs"]
            handoff_dump["experiment_execution_state"] = evaluation["experiment_execution_state"]
            output["evaluation"] = evaluation

        return output, payload, parse_status

    @classmethod
    def _detect_constraint_violations(cls, context: RuntimeContext, final_text: str) -> List[str]:
        """Deterministic hard-constraint violation scan for Final CMO output.

        Minimal scope: publish-prohibition vs auto-publish authorization.
        Medical/product claim violations are already enforced by the
        COLLAB-02 factual-claim firewall and are not duplicated here.
        """
        violations: List[str] = []
        lowered_final = (final_text or "").lower()
        for constraint in context.constraints:
            lowered_constraint = constraint.lower()
            prohibits_publishing = (
                "publish" in lowered_constraint or "đăng bài" in lowered_constraint or "đăng nội dung" in lowered_constraint
            )
            if prohibits_publishing:
                if any(phrase in lowered_final for phrase in _FORBIDDEN_AUTO_PUBLISH_PHRASES):
                    violations.append(
                        f"CONSTRAINT_VIOLATION: final plan authorizes automatic/immediate publication "
                        f"despite binding restriction '{constraint[:120]}'."
                    )
        return violations

    @classmethod
    def _detect_performance_inconclusive(cls, perf_out: Dict[str, Any]) -> bool:
        """Deterministic INCONCLUSIVE detection from the Performance stage output."""
        if not isinstance(perf_out, dict):
            return False
        corpus_parts = [
            perf_out.get("funnel_kpi") or "",
            json.dumps(perf_out.get("experiment_blueprint") or {}, ensure_ascii=False),
        ]
        corpus = " ".join(str(p) for p in corpus_parts).lower()
        return any(marker in corpus for marker in cls._INCONCLUSIVE_MARKERS)

    @classmethod
    def _scan_phantom_performance_claims(
        cls,
        text: str,
        execution_state: str,
        eval_status: str,
        eval_origin: str,
    ) -> List[str]:
        """Scan prose for empirical performance result/winner claims when no qualifying observed result exists."""
        if not text or not isinstance(text, str):
            return []
        reasons: List[str] = []
        for sentence in re.split(r"(?<=[.!?\n])\s+", text):
            clean = sentence.strip()
            if not clean or len(clean) < 3:
                continue
            is_conditional = bool(cls._PLANNING_OR_CONDITIONAL_PERFORMANCE_PATTERN.search(clean))
            for pat in cls._OBSERVED_PERFORMANCE_RESULT_PATTERNS:
                if pat.search(clean):
                    # If it has planning/conditional markers and is not an explicit past-tense winner/validation statement, preserve planning
                    if is_conditional and not re.search(r"\b(?:won|winner|succeeded|validated|after\s+the\s+test|post-test|results\s+from\s+the)\b", clean, re.IGNORECASE):
                        continue
                    reasons.append(
                        f"PHANTOM_WINNER: observed performance result or winner claimed ('{clean[:120]}') "
                        f"while experiment_execution_state={execution_state}, evaluation_status={eval_status}, "
                        f"data_origin={eval_origin}; no qualifying REAL evidence exists in this run."
                    )
                    break
        return reasons

    @classmethod
    def _is_material_factual_claim(cls, sentence: str) -> bool:
        """Check if a sentence matches any material factual claim pattern."""
        for pat in cls._FACTUAL_CLAIM_PATTERNS:
            if pat.search(sentence):
                return True
        return False

    @classmethod
    def _is_planning_or_hypothesis(cls, sentence: str) -> bool:
        """Check if a sentence is explicitly framed as hypothesis or planning."""
        lowered = sentence.lower()
        if any(m in lowered for m in cls._HYPOTHESIS_MARKERS):
            return True
        if any(m in lowered for m in cls._PLANNING_MARKERS):
            return True
        return False

    @classmethod
    def _scan_unsupported_product_claims(
        cls,
        corpus_text: str,
        provenance_index: Dict[str, Any],
    ) -> tuple[int, int, int, List[str], Dict[str, str]]:
        """Scan free text for factual/product claims lacking verified support.

        Creative propositions (hypotheses, ideas, placeholders) are preserved
        and never blocked. A factual-pattern claim passes ONLY when it cites a
        source id present in the provenance index whose epistemic tier is
        VERIFIED_SOURCE or SOURCE_BACKED_OBSERVATION (mock/sandbox/failed
        receipts can never satisfy this requirement).
        """
        total = supported = hypotheses = blocked = 0
        blocking_reasons: List[str] = []
        claim_actions: Dict[str, str] = {}

        for sentence in re.split(r"(?<=[.!?\n])\s+", corpus_text or ""):
            clean_sentence = sentence.strip()
            if not clean_sentence or len(clean_sentence) < 3:
                continue

            if not cls._is_material_factual_claim(clean_sentence):
                continue

            total += 1
            label = f"claim_{total}"

            # Evidence check FIRST: a cited source with insufficient tier is an
            # evidence failure and must block even if wording contains
            # hypothesis-like markers (e.g., a source id containing "mock").
            citation = cls._SOURCE_CITATION_PATTERN.search(clean_sentence)
            cited_id = citation.group(1).upper() if citation else None
            evidence_item = provenance_index.get(cited_id) if cited_id else None
            tier = ""
            if isinstance(evidence_item, dict):
                tier = str(evidence_item.get("epistemic_tier", "")).upper()
            elif evidence_item is not None:
                tier = str(getattr(evidence_item, "epistemic_tier", "")).upper().replace("EPISTEMICTIER.", "")

            if tier in cls._DEPLOYABLE_EVIDENCE_TIERS:
                supported += 1
                claim_actions[label] = "AUTHORIZE"
                continue

            if cited_id:
                blocked += 1
                claim_actions[label] = "BLOCK_PUBLICATION"
                blocking_reasons.append(
                    f"UNSUPPORTED_PRODUCT_CLAIM [{label}]: '{clean_sentence[:140]}' "
                    f"cites source '{cited_id}' whose tier '{tier or 'NONE'}' cannot "
                    f"authorize deployment."
                )
                continue

            if cls._is_planning_or_hypothesis(clean_sentence):
                hypotheses += 1
                claim_actions[label] = "PRESERVE_HYPOTHESIS"
                continue

            blocked += 1
            claim_actions[label] = "BLOCK_PUBLICATION"
            blocking_reasons.append(
                f"UNSUPPORTED_PRODUCT_CLAIM [{label}]: '{clean_sentence[:140]}' "
                f"lacks a citable verified/live-tool source (tier found: {tier or 'NONE'})."
            )

        return total, supported, hypotheses, blocking_reasons, claim_actions

    def _evaluate_final_authorization(
        self,
        context: RuntimeContext,
        perf_out: Dict[str, Any],
        crtv_out: Dict[str, Any],
        final_text: str,
    ) -> FinalClaimAuditGateResult:
        """Fail-closed pre-deployment audit for the Final CMO output."""
        blocking_reasons: List[str] = []
        claim_actions: Dict[str, str] = {}
        blocked = 0

        if self._detect_performance_inconclusive(perf_out):
            blocked += 1
            claim_actions["performance"] = "HOLD"
            blocking_reasons.append(
                "PERFORMANCE_INCONCLUSIVE: Performance reported an inconclusive/"
                "insufficient-evidence result; deployment cannot be authorized."
            )

        # COLLAB-06 / GOV-02: structural (prose-independent) performance state.
        perf_handoff = (context.working_state.get("stage_handoffs", {}) or {}).get("performance", {}) or {}
        if isinstance(perf_handoff, dict):
            if perf_handoff.get("performance_inconclusive"):
                blocked += 1
                blocking_reasons.append(
                    "PERFORMANCE_INCONCLUSIVE_STRUCTURAL: Performance handoff carries an "
                    "INCONCLUSIVE flag; prose cannot override it."
                )
            execution_state = str(perf_handoff.get("experiment_execution_state", "EXPERIMENT_PROPOSED")).upper()
            eval_status = str(perf_handoff.get("evaluation_status", "NOT_EVALUATED")).upper()
            eval_origin = str(perf_handoff.get("evaluation_data_origin", "NO_DATA")).upper()

            has_valid_observed_result = (
                execution_state == "RESULT_OBSERVED"
                and eval_status in ("SUPPORTED", "NOT_SUPPORTED")
                and eval_origin == "REAL"
            )

            if not has_valid_observed_result:
                phantom_reasons = self._scan_phantom_performance_claims(
                    final_text or "",
                    execution_state=execution_state,
                    eval_status=eval_status,
                    eval_origin=eval_origin,
                )
                if phantom_reasons:
                    blocked += len(phantom_reasons)
                    blocking_reasons.extend(phantom_reasons)

        # Structured claim checks from handoffs
        stage_handoffs = context.working_state.get("stage_handoffs", {}) or {}
        for s_key, s_handoff in stage_handoffs.items():
            if isinstance(s_handoff, dict):
                s_claims = s_handoff.get("claims") or s_handoff.get("material_claims") or []
                if isinstance(s_claims, list):
                    for c_item in s_claims:
                        if isinstance(c_item, dict):
                            c_class = str(c_item.get("claim_class", "")).upper().replace("CLAIMCLASS.", "")
                            c_usage = str(c_item.get("allowed_usage", "")).upper().replace("ALLOWEDUSAGE.", "")
                            c_support = str(c_item.get("support_status", "")).upper().replace("SUPPORTSTATUS.", "")
                            c_id = c_item.get("claim_id", "STRUCTURED_CLAIM")
                            c_text = c_item.get("claim_text", "")

                            if (c_class in ("VERIFIED_PRODUCT_FACT", "BUSINESS_FACT") or c_usage == "PUBLIC_CLAIM") and c_support in ("UNSUPPORTED", "UNKNOWN", ""):
                                blocked += 1
                                blocking_reasons.append(
                                    f"UNSUPPORTED_STRUCTURED_CLAIM [{c_id}]: '{c_text[:140]}' is structured as {c_class}/{c_usage} but support_status is {c_support or 'UNSUPPORTED'}."
                                )
                                claim_actions[c_id] = "BLOCK_PUBLICATION"

        provenance_index = context.working_state.get("provenance_index", {}) or {}
        creative_text_parts = [
            str(crtv_out.get("creative_synthesis") or ""),
            final_text,
        ]
        corpus = " ".join(part for part in creative_text_parts if part)
        total, supported, hypotheses, claim_reasons, claim_actions_scan = (
            self._scan_unsupported_product_claims(corpus, provenance_index)
        )
        blocking_reasons.extend(claim_reasons)
        claim_actions.update(claim_actions_scan)
        blocked += len(claim_reasons)

        constraint_violations = self._detect_constraint_violations(context, final_text)
        blocking_reasons.extend(constraint_violations)
        blocked += len(constraint_violations)

        if blocked > 0:
            authorization_status = "BLOCKED"
        elif hypotheses > 0:
            authorization_status = "APPROVED_WITH_CONDITIONS"
        else:
            authorization_status = "APPROVED"

        return FinalClaimAuditGateResult(
            total_claims=total,
            supported_claims=supported,
            unknown_claims=0,
            hypotheses_count=hypotheses,
            blocked_claims=blocked,
            human_input_required_count=0,
            authorization_status=authorization_status,
            blocking_reasons=blocking_reasons,
            claim_actions=claim_actions,
        )

    @staticmethod
    def _fail_closed_audit(reason_code: str, detail: str) -> FinalClaimAuditGateResult:
        """Deterministic fail-closed audit result for gate errors / missing audits."""
        return FinalClaimAuditGateResult(
            total_claims=0,
            supported_claims=0,
            unknown_claims=0,
            hypotheses_count=0,
            blocked_claims=1,
            human_input_required_count=0,
            authorization_status="BLOCKED",
            blocking_reasons=[f"{reason_code}: {detail}"],
            claim_actions={"audit": "FAIL_CLOSED"},
        )

    def execute_stage_final_cmo(self, context: RuntimeContext) -> Dict[str, Any]:
        """Stage 6: Governed Final CMO Synthesis & Master GTM Plan."""
        context.current_stage = RuntimeStage.FINAL_CMO

        cmo_init = context.stage_outputs.get("cmo_initial", {})
        intel_out = context.stage_outputs.get("intelligence", {})
        strat_out = context.stage_outputs.get("strategist", {})
        crtv_out = context.stage_outputs.get("creative", {})
        perf_out = context.stage_outputs.get("performance", {})

        has_stage_failure = any(
            s.get("status") == "FAILED" for s in (cmo_init, intel_out, strat_out, crtv_out, perf_out)
        ) or context.status == RuntimeStatus.FAILED

        if has_stage_failure:
            fail_reason = "PREVIOUS_STAGE_FAILED"
            context.status = RuntimeStatus.FAILED
            output = {
                "stage": "FINAL_CMO",
                "agent": "cmo",
                "status": "FAILED",
                "approval_status": "NOT_EVALUATED",
                "reason": fail_reason,
                "master_gtm_plan": {},
                "master_gtm_plan_markdown": f"# BÁO CÁO PHÊ DUYỆT THẤT BẠI — FIVE-AGENT DEPARTMENT\n\n**Trạng thái phê duyệt**: KHÔNG ĐƯỢC PHÊ DUYỆT ({fail_reason})\n\nKhông thể hoàn tất kế hoạch GTM do một hoặc nhiều giai đoạn chuyên môn trước đó gặp sự cố.",
            }
            context.stage_outputs["final_cmo"] = output
            context.create_checkpoint()
            return output

        # Grounded Context Compilation for Final CMO
        grounded_pkg = self.context_compiler.compile_grounded_package("cmo", context)
        prov_map = context.working_state.setdefault("provenance_index", {})
        for sid, item in grounded_pkg.provenance_index.items():
            prov_map[sid] = item.model_dump()

        # Dynamic LLM Final CMO Master Synthesis
        sys_prompt = (
            "You are the Chief Marketing Officer (CMO) delivering the Final Governed Go-To-Market (GTM) Strategy & Execution Plan.\n"
            "Synthesize all specialist deliverables into an executive, beautifully formatted Markdown report containing:\n"
            "1. # Executive Summary & Strategic Intent\n"
            "2. ## Market Intelligence & Competitor Signals (from Intelligence)\n"
            "3. ## Positioning Architecture & ICP Target Segments (from Strategist)\n"
            "4. ## Creative Concepts, Ad Hooks & Video Scripts (from Creative)\n"
            "5. ## Media Allocation, Full-Funnel KPIs & Experiment Backlog (from Performance)\n"
            "6. ## Governance, Autonomy & Next Action Steps\n\n"
            "CRITICAL: Always output complete, professional Markdown with headers, tables, and bullet points. "
            "Never output raw Python dictionaries. "
            "Mirror the exact language of the user objective (Vietnamese if user wrote Vietnamese, English if English)."
        )

        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = (
            f"User Commercial Objective: {context.objective}\n\n"
            f"Specialist Deliverables:\n"
            f"- CMO Strategic Intent: {cmo_init.get('strategic_intent', '')}\n"
            f"- Intelligence Findings: {intel_out.get('market_findings', '')}\n"
            f"- Strategist Positioning: {strat_out.get('positioning', '')}\n"
            f"- Creative Synthesis: {crtv_out.get('creative_synthesis', crtv_out.get('copy_headlines', ''))}\n"
            f"- Performance Plan: {perf_out.get('funnel_kpi', '')}\n\n"
            f"{evidence_section}"
        ).strip()
        user_prompt = self._append_governance_block(context, user_prompt)

        llm_report, err = self._call_agent_llm("cmo", sys_prompt, user_prompt)

        if not llm_report:
            fail_reason = err or "MODEL_PROVIDER_FAILURE"
            context.status = RuntimeStatus.FAILED
            context.risk_flags.append(f"FINAL_CMO_FAILED: {fail_reason}")
            output = {
                "stage": "FINAL_CMO",
                "agent": "cmo",
                "status": "FAILED",
                "approval_status": "NOT_EVALUATED",
                "reason": fail_reason,
                "master_gtm_plan": {},
                "master_gtm_plan_markdown": f"# BÁO CÁO PHÊ DUYỆT THẤT BẠI — FIVE-AGENT DEPARTMENT\n\n**Trạng thái phê duyệt**: KHÔNG ĐƯỢC PHÊ DUYỆT ({fail_reason})\n\nKhông thể hoàn tất đánh giá và phê duyệt chiến dịch do lỗi kết nối hoặc gián đoạn dịch vụ mô hình AI.",
            }
            context.stage_outputs["final_cmo"] = output
            context.create_checkpoint()
            return output

        if not llm_report.strip().startswith("#"):
            llm_report = f"# BÁO CÁO CHIẾN LƯỢC GTM — {context.objective}\n\n{llm_report}"

        # ------------------------------------------------------------------
        # COLLAB-02: Fail-closed authorization gate (runs exactly once).
        # The Final CMO LLM is NOT the authorization authority. Any gate
        # error, missing audit result, Performance INCONCLUSIVE, or
        # unsupported product claim blocks deployment. Raw LLM output is
        # preserved verbatim regardless of the decision.
        # ------------------------------------------------------------------
        try:
            audit_res = self._evaluate_final_authorization(context, perf_out, crtv_out, llm_report)
        except Exception as audit_err:
            audit_res = self._fail_closed_audit("AUDIT_GATE_ERROR", str(audit_err))
        if audit_res is None:
            audit_res = self._fail_closed_audit("MISSING_AUDIT_RESULT", "Authorization audit produced no result.")

        approved_for_deployment = audit_res.authorization_status in ("APPROVED", "APPROVED_WITH_CONDITIONS")
        if not approved_for_deployment:
            context.status = RuntimeStatus.FAILED
            joined_reasons = "; ".join(audit_res.blocking_reasons)[:400]
            context.risk_flags.append(f"FINAL_CMO_NOT_AUTHORIZED: {joined_reasons}")

        output = {
            "stage": "FINAL_CMO",
            "agent": "cmo",
            "status": "READY_FOR_DEPLOYMENT" if approved_for_deployment else "NOT_READY",
            "approval_status": audit_res.authorization_status,
            "reason": "" if approved_for_deployment else "; ".join(audit_res.blocking_reasons)[:300],
            "claim_audit": audit_res.model_dump(),
            "master_gtm_plan": {
                "objective": context.objective,
                "strategy": strat_out,
                "creative": crtv_out,
                "performance": perf_out,
            },
            "master_gtm_plan_markdown": llm_report,
        }
        output, _payload, _parse_status = self._finalize_stage_handoff(context, "final_cmo", "cmo", llm_report, output)
        context.stage_outputs["final_cmo"] = output
        context.create_checkpoint()
        return output

    def request_publish_action(self, context: RuntimeContext, platform: str = "linkedin", approval_token: Optional[str] = None) -> ExecutionReceipt:
        """Attempt to execute a publishing action, triggering Human Approval Gate if unapproved."""
        pub_req = ToolRequest(
            run_id=context.run_id,
            agent_id="cmo",
            capability_id="social_publishing",
            parameters={"platform": platform, "content": "Campaign Go-To-Market Plan"},
            approval_token=approval_token,
        )
        receipt = self.tool_gateway.execute(pub_req)
        context.execution_receipt_refs.append(receipt.execution_id)
        self.lineage_inspector.add_receipt(receipt)

        if receipt.status == ExecutionStatus.APPROVAL_REQUIRED:
            context.status = RuntimeStatus.WAITING_FOR_APPROVAL
            context.create_checkpoint(pending_approval_id=receipt.execution_id)
        elif receipt.status == ExecutionStatus.SUCCESS:
            context.status = RuntimeStatus.RUNNING
            context.create_checkpoint()

        return receipt

    def complete_run(self, context: RuntimeContext) -> DepartmentRunArtifact:
        """Finalize the supervised run, record candidate memories and produce sealed artifact."""
        context.current_stage = RuntimeStage.COMPLETED
        if context.status != RuntimeStatus.FAILED:
            context.status = RuntimeStatus.COMPLETED
        completed_at = datetime.now(timezone.utc)

        # 1. Propose Memory Candidates only if run completed successfully.
        # COLLAB-04: template memories removed. Exactly ONE factual
        # decision-bookkeeping record is written, and ONLY when the run truly
        # reached deployment-ready state. No success language, no invented
        # experiments, no fabricated confidence (bookkeeping value only).
        cand_memories: List[MemoryWriteCandidate] = []
        if context.status == RuntimeStatus.COMPLETED:
            final_out = context.stage_outputs.get("final_cmo", {})
            if final_out.get("status") == "READY_FOR_DEPLOYMENT":
                cand_memories = [
                    MemoryWriteCandidate(
                        memory_type=MemoryType.DECISION_MEMORY,
                        agent_source="cmo",
                        content=(
                            f"GTM plan reached deployment-ready state for objective: {context.objective}"
                        ),
                        context={
                            "record_type": "RUN_DECISION_BOOKKEEPING",
                            "approval_status": final_out.get("approval_status"),
                            "business_id": context.business_id,
                            "campaign_id": context.campaign_id,
                        },
                        evidence_refs=list(context.execution_receipt_refs),
                        confidence=CANDIDATE_BOOKKEEPING_CONFIDENCE,
                        target_initial_state=PromotionState.CANDIDATE_MEMORY,
                    ),
                ]

            # Write to Memory Repository without automatic promotion
            for cand in cand_memories:
                mem_item = cand.to_memory_item(context.run_id)
                self.memory_repo.save_memory(mem_item)

        # 2. Phase 1A Hardening: Automatic empirical learning creation from arbitrary working_state is disabled.
        # Verified evidence-based ingestion will be implemented in Phase 1B.

        # 3. Assemble DepartmentRunArtifact
        receipts = [self.tool_gateway.receipt_repository.get_receipt(r_id) for r_id in context.execution_receipt_refs]
        valid_receipts = [r for r in receipts if r is not None]

        artifact = DepartmentRunArtifact(
            run_id=context.run_id,
            objective=context.objective,
            started_at=context.created_at,
            completed_at=completed_at,
            status=context.status,
            agent_outputs=context.stage_outputs,
            knowledge_used=context.knowledge_refs,
            memory_used=context.memory_refs,
            capabilities_used=[r.capability_id for r in valid_receipts],
            execution_receipts=valid_receipts,
            approvals=[],
            artifacts=context.artifact_refs,
            learning_candidates=cand_memories,
            final_cmo_output=context.stage_outputs.get("final_cmo", {}),
            lineage_summary={"citations": [c.citation_id for c in self.lineage_inspector.get_all_citations()]},
            binding_constraints=list(context.constraints),
            epistemic_handoffs=dict(context.working_state.get("stage_handoffs", {})),
            errors=context.risk_flags,
        )
        artifact.final_artifact_hash = artifact.compute_artifact_hash()

        self._completed_runs[context.run_id] = artifact
        return artifact
