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
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from governance.access_matrix import AgentAccessMatrix
from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from knowledge.models import KnowledgeCitation
from knowledge.repository import KnowledgeRepository, LocalKnowledgeRepository
from memory.learning import LearningEvent, LearningRepository, LocalLearningRepository
from memory.models import MemoryItem, MemoryType, PromotionState
from memory.repository import LocalMemoryRepository, MemoryRepository
from chat.knowledge import SessionKnowledgeStore
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
from runtime.knowledge_builder import KnowledgeContextBuilder
from runtime.lineage import LineageInspector
from runtime.memory_builder import MemoryContextBuilder
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest

logger = logging.getLogger("department_runtime")


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
                "intelligence_focus": f"Investigate market landscape, customer pain points, and competitors for {context.objective}",
                "strategist_focus": f"Define ICP segments, value proposition, and positioning hierarchy for {context.objective}",
                "creative_focus": f"Develop creative angles, high-converting hooks, and ad copy for {context.objective}",
                "performance_focus": f"Establish CAC/ROAS targets, channel mix, and experiment roadmap for {context.objective}",
            },
            "citations": [c.citation_id for c in k_res.citations],
        }
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
            "target_segments": ["Primary High-Intent Decision Makers", "Growth-Oriented Adopters"],
            "value_propositions": ["Differentiated performance", "Verified customer outcomes"],
            "citations": [c.citation_id for c in k_res.citations],
        }
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
            "concept_name": "Direct Response & Brand Affinity Concept",
            "visual_asset_receipt": img_receipt.execution_id,
            "creative_synthesis": llm_creative,
            "copy_headlines": [llm_creative],
            "citations": [c.citation_id for c in k_res.citations],
        }
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
        concept = context.stage_outputs.get("creative", {}).get("concept_name", "")
        evidence_section = grounded_pkg.render_prompt_section()
        user_prompt = f"Objective: {context.objective}\nStrategy: {strat_pos}\nCreative Assets: {concept}\n\n{evidence_section}".strip()
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
            "experiment_blueprint": {
                "hypothesis": f"Optimized creative hooks and segmented targeting improve CVR for {context.objective}",
                "metric": "cvr_step_1",
            },
            "calc_receipt_id": calc_receipt.execution_id,
            "citations": [c.citation_id for c in k_res.citations],
        }
        context.stage_outputs["performance"] = output
        context.create_checkpoint()
        return output

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

        output = {
            "stage": "FINAL_CMO",
            "agent": "cmo",
            "status": "READY_FOR_DEPLOYMENT",
            "approval_status": "APPROVED",
            "master_gtm_plan": {
                "objective": context.objective,
                "strategy": strat_out,
                "creative": crtv_out,
                "performance": perf_out,
            },
            "master_gtm_plan_markdown": llm_report,
        }
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

        # 1. Propose Memory Candidates only if run completed successfully
        cand_memories: List[MemoryWriteCandidate] = []
        if context.status == RuntimeStatus.COMPLETED:
            cand_memories = [
                MemoryWriteCandidate(
                    memory_type=MemoryType.DECISION_MEMORY,
                    agent_source="cmo",
                    content=f"Approved strategic direction for objective: {context.objective}",
                    context={"business_id": context.business_id, "campaign_id": context.campaign_id},
                    confidence=0.75,
                    target_initial_state=PromotionState.CANDIDATE_MEMORY,
                ),
                MemoryWriteCandidate(
                    memory_type=MemoryType.EXPERIMENT_MEMORY,
                    agent_source="performance",
                    content=f"Hypothesis: Targeted messaging improves CVR for {context.objective}.",
                    context={"metric": "cvr_step_1"},
                    confidence=0.70,
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
            errors=context.risk_flags,
        )
        artifact.final_artifact_hash = artifact.compute_artifact_hash()

        self._completed_runs[context.run_id] = artifact
        return artifact
