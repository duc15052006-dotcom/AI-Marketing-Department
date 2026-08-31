"""Context Compiler for AI Marketing Department.

Assembles bounded, role-targeted grounded context packages for each of the Five Permanent Agents
from ephemeral session attachments, scoped persistent brand/project/global knowledge,
filtered institutional memories, and ToolGateway execution receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chat.knowledge import SessionKnowledgeStore
from governance.access_matrix import AgentAccessMatrix
from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import KnowledgeRepository, LocalKnowledgeRepository
from memory.models import MemoryItem, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.repository import LocalMemoryRepository, MemoryRepository
from runtime.context import EpistemicTier, EvidenceItem, GroundedContextPackage, RuntimeContext
from tools.capabilities import CapabilityRegistry, EvidenceRole
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


@dataclass
class AgentCompiledContext:
    """Targeted, bounded prompt and reference context for an individual agent (legacy view)."""

    agent_id: str
    objective: str
    conversation_summary: str = ""
    session_knowledge_chunks: List[str] = field(default_factory=list)
    persistent_knowledge_refs: List[str] = field(default_factory=list)
    memory_citations: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    raw_prompt_payload: str = ""

    def model_dump(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "objective": self.objective,
            "conversation_summary": self.conversation_summary,
            "session_knowledge_chunks": self.session_knowledge_chunks,
            "persistent_knowledge_refs": self.persistent_knowledge_refs,
            "memory_citations": self.memory_citations,
            "constraints": self.constraints,
            "raw_prompt_payload": self.raw_prompt_payload,
        }


class ContextCompiler:
    """Compiles strictly bounded role-specific GroundedContextPackages across all available evidence layers."""

    def __init__(
        self,
        session_knowledge: Optional[SessionKnowledgeStore] = None,
        knowledge_repo: Optional[KnowledgeRepository] = None,
        memory_repo: Optional[MemoryRepository] = None,
        capability_registry: Optional[CapabilityRegistry] = None,
    ) -> None:
        self.session_knowledge = session_knowledge or SessionKnowledgeStore()
        self.knowledge_repo = knowledge_repo or LocalKnowledgeRepository()
        self.memory_repo = memory_repo or LocalMemoryRepository()
        self.capability_registry = capability_registry or CapabilityRegistry()

    def compile_grounded_package(
        self,
        agent_id: str,
        ctx: RuntimeContext,
        tool_receipts: Optional[List[ExecutionReceipt]] = None,
        stage_inputs: Optional[Dict[str, Any]] = None,
        char_budget: int = 10000,
    ) -> GroundedContextPackage:
        """Compile a role-targeted GroundedContextPackage with strict scope isolation and epistemic tiers."""
        aid = agent_id.lower()
        run_prefix = ctx.run_id[:8] if ctx.run_id else "RUN000"
        evidence_items: List[EvidenceItem] = []
        item_counter = 1

        # ---------------------------------------------------------------------
        # 1. Ephemeral Session Knowledge (Attachments) — Strictly scoped to chat_id
        # ---------------------------------------------------------------------
        if ctx.chat_id and self.session_knowledge:
            session_chunks = self.session_knowledge.search_session(
                ctx.chat_id,
                query=ctx.objective,
                top_k=5,
            )
            for ch in session_chunks:
                sid = f"ATT-{run_prefix}-{item_counter:03d}"
                item_counter += 1
                evidence_items.append(
                    EvidenceItem(
                        source_id=sid,
                        epistemic_tier=EpistemicTier.UNVERIFIED_SOURCE,
                        source_type="SESSION_ATTACHMENT",
                        scope=f"SESSION_{ctx.chat_id}",
                        title_or_reference=f"Attachment Chunk [{ch.chunk_id}] (Doc: {ch.attachment_id})",
                        content=ch.text,
                        original_length=len(ch.text),
                        included_length=len(ch.text),
                        metadata={"chat_id": ctx.chat_id, "attachment_id": ch.attachment_id, "chunk_id": ch.chunk_id},
                    )
                )

        # ---------------------------------------------------------------------
        # 2. Scoped Persistent Knowledge — Strictly scoped (GLOBAL, Business, Project)
        # ---------------------------------------------------------------------
        if self.knowledge_repo:
            prof = AgentAccessMatrix.get_profile(aid)
            allowed_sources = prof.allowed_knowledge_sources if prof else [SourceType.CANONICAL_FACT, SourceType.VERIFIED_EVIDENCE]

            # Build strictly permitted scopes (Never retrieve un-scoped / wildcard).
            # OperatorWorkspace may bind an explicit per-business scope in working_state;
            # honor it as the current workspace boundary, otherwise use the canonical
            # business-id-derived scope used by direct runtime callers.
            scopes = ["GLOBAL"]
            configured_knowledge_scope = str(ctx.working_state.get("knowledge_scope") or "").strip()
            if configured_knowledge_scope and configured_knowledge_scope != "GLOBAL":
                scopes.append(configured_knowledge_scope)
            elif ctx.business_id and ctx.business_id not in ("GLOBAL", "BIZ_DEFAULT"):
                scopes.append(f"SCOPE_{ctx.business_id}")
            elif ctx.business_id == "BIZ_DEFAULT":
                scopes.append("SCOPE_BIZ_DEFAULT")

            if ctx.project_id:
                scopes.append(f"SCOPE_PROJ_{ctx.project_id}")

            seen_knowledge_ids: set = set()
            for s in scopes:
                scoped_docs = self.knowledge_repo.list_documents(scope=s)
                valid_docs = [d for d in scoped_docs if d.source_type in allowed_sources and d.freshness != "RETIRED"]
                for doc in valid_docs[:4]:
                    if doc.knowledge_id in seen_knowledge_ids:
                        continue
                    seen_knowledge_ids.add(doc.knowledge_id)
                    # Map canonical authority level to EpistemicTier
                    if doc.authority_level in (AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH, AuthorityLevel.TIER_2_VERIFIED_RESEARCH):
                        tier = EpistemicTier.VERIFIED_SOURCE
                    else:
                        tier = EpistemicTier.UNVERIFIED_SOURCE

                    sid = f"SRC-{run_prefix}-{item_counter:03d}"
                    item_counter += 1
                    raw_text = doc.content
                    evidence_items.append(
                        EvidenceItem(
                            source_id=sid,
                            epistemic_tier=tier,
                            source_type=doc.source_type.value if hasattr(doc.source_type, "value") else str(doc.source_type),
                            scope=doc.scope or s,
                            title_or_reference=f"Knowledge Doc: {doc.title} (ID: {doc.knowledge_id}, Auth: {doc.authority_level.value})",
                            content=raw_text,
                            original_length=len(raw_text),
                            included_length=len(raw_text),
                            metadata={"knowledge_id": doc.knowledge_id, "version": doc.version, "authority": doc.authority_level.value},
                        )
                    )

        # ---------------------------------------------------------------------
        # 3. Institutional Memory — Strictly separating VERIFIED from CANDIDATE
        # ---------------------------------------------------------------------
        if self.memory_repo:
            prof = AgentAccessMatrix.get_profile(aid)
            allowed_types = prof.allowed_memory_types if prof else []
            min_conf = ctx.memory_policy.get("min_confidence", 0.60) if ctx.memory_policy else 0.60

            # Bounded memory scope. OperatorWorkspace may provide a configured
            # business memory scope; direct runtime callers retain the existing
            # business-id-derived fallback semantics.
            configured_memory_scope = str(ctx.working_state.get("memory_scope") or "").strip()
            if configured_memory_scope:
                scope_target = configured_memory_scope
            else:
                scope_target = f"SCOPE_{ctx.business_id}" if ctx.business_id and ctx.business_id != "BIZ_DEFAULT" else "GLOBAL"
            all_mems = self.memory_repo.list_memories()

            for m in all_mems:
                if getattr(m, "scope", "GLOBAL") not in (scope_target, "GLOBAL"):
                    continue
                if m.memory_type not in allowed_types:
                    continue
                if m.confidence < min_conf:
                    continue
                if MemoryPromotionEngine.audit_memory_staleness(m):
                    continue

                if m.promotion_level in (PromotionState.VERIFIED_MEMORY, PromotionState.PROMOTED_LEARNING):
                    tier = EpistemicTier.VERIFIED_MEMORY
                else:
                    tier = EpistemicTier.CANDIDATE_MEMORY

                sid = f"MEM-{run_prefix}-{item_counter:03d}"
                item_counter += 1
                mem_text = f"[{m.memory_type.value} | Agent: {m.agent_source} | Conf: {m.confidence:.2f}]\n{m.content}"
                evidence_items.append(
                    EvidenceItem(
                        source_id=sid,
                        epistemic_tier=tier,
                        source_type="INSTITUTIONAL_MEMORY",
                        scope=getattr(m, "scope", "GLOBAL"),
                        title_or_reference=f"Memory Ref [{m.memory_id}] ({tier.value})",
                        content=mem_text,
                        original_length=len(mem_text),
                        included_length=len(mem_text),
                        metadata={"memory_id": m.memory_id, "promotion_level": m.promotion_level.value, "confidence": m.confidence},
                    )
                )

        # ---------------------------------------------------------------------
        # 4. ToolGateway Execution Results — Preserving REAL vs MOCK/SANDBOX & EvidenceRole
        # ---------------------------------------------------------------------
        if tool_receipts:
            for receipt in tool_receipts:
                if receipt.status != ExecutionStatus.SUCCESS:
                    # Failed / blocked / timeout tool execution does NOT produce factual evidence
                    continue

                mode = getattr(receipt, "execution_mode", ExecutionMode.MOCK)
                is_real = (mode == ExecutionMode.REAL or str(mode).upper() in ("REAL", "EXECUTIONMODE.REAL"))

                # Capability evidence role lookup
                cap = self.capability_registry.get_capability(receipt.capability_id) if self.capability_registry else None
                evidence_role = getattr(cap, "evidence_role", EvidenceRole.NONE) if cap else EvidenceRole.NONE
                if isinstance(evidence_role, str):
                    try:
                        evidence_role = EvidenceRole(evidence_role.upper())
                    except ValueError:
                        evidence_role = EvidenceRole.NONE

                # Only OBSERVATION role capabilities can produce EvidenceItems
                if evidence_role != EvidenceRole.OBSERVATION:
                    # ACTION, COMPUTATION, GENERATIVE, NONE receipts do NOT create EvidenceItems.
                    # They remain immutably preserved in ExecutionReceiptRepository, RuntimeContext.execution_receipt_refs,
                    # lineage_inspector, and DepartmentRunArtifact.execution_receipts with their truthful execution_mode.
                    continue

                # For OBSERVATION capabilities:
                if is_real:
                    tier = EpistemicTier.SOURCE_BACKED_OBSERVATION
                    title_prefix = f"Live Tool Observation ({receipt.capability_id})"
                else:
                    # MOCK or SANDBOX observation (e.g. simulated web_search)
                    tier = EpistemicTier.MOCK_OR_SANDBOX
                    title_prefix = f"Simulated Tool Output ({mode.value if hasattr(mode, 'value') else mode})"

                # Format actual result content (consume receipt.output or receipt.data)
                payload = receipt.output if receipt.output is not None else receipt.data
                if isinstance(payload, (dict, list)):
                    formatted_content = json.dumps(payload, indent=2, ensure_ascii=False)
                elif payload is not None:
                    formatted_content = str(payload)
                else:
                    formatted_content = "{}"

                res_hash = getattr(receipt, "result_hash", "") or (receipt.calculate_result_hash() if hasattr(receipt, "calculate_result_hash") else "")

                sid = f"TOOL-{run_prefix}-{item_counter:03d}"
                item_counter += 1
                evidence_items.append(
                    EvidenceItem(
                        source_id=sid,
                        epistemic_tier=tier,
                        source_type="TOOL_RECEIPT",
                        scope=f"SCOPE_{ctx.business_id}" if ctx.business_id else "GLOBAL",
                        title_or_reference=f"{title_prefix} [Receipt: {receipt.execution_id} | Cap: {receipt.capability_id}]",
                        content=formatted_content,
                        original_length=len(formatted_content),
                        included_length=len(formatted_content),
                        metadata={
                            "receipt_id": receipt.execution_id,
                            "run_id": getattr(receipt, "run_id", ctx.run_id),
                            "capability_id": receipt.capability_id,
                            "evidence_role": evidence_role.value if hasattr(evidence_role, "value") else str(evidence_role),
                            "provider": receipt.provider,
                            "execution_mode": mode.value if hasattr(mode, "value") else str(mode),
                            "status": receipt.status.value if hasattr(receipt.status, "value") else str(receipt.status),
                            "result_hash": res_hash,
                        },
                    )
                )

        # ---------------------------------------------------------------------
        # 5. Token / Character Budgeting with Priority Allocation
        # ---------------------------------------------------------------------
        def _tier_priority(item: EvidenceItem) -> int:
            if item.epistemic_tier == EpistemicTier.VERIFIED_SOURCE:
                return 1
            if item.epistemic_tier == EpistemicTier.SOURCE_BACKED_OBSERVATION:
                return 2
            if item.epistemic_tier == EpistemicTier.VERIFIED_MEMORY:
                return 3
            if item.epistemic_tier == EpistemicTier.MOCK_OR_SANDBOX:
                return 4
            if item.epistemic_tier == EpistemicTier.UNVERIFIED_SOURCE:
                return 5
            return 6

        evidence_items.sort(key=_tier_priority)

        current_total_chars = 0
        final_items: List[EvidenceItem] = []
        truncated_count = 0

        for item in evidence_items:
            item_len = len(item.content)
            available = char_budget - current_total_chars

            if available <= 100:
                # No budget remaining for this item
                item.truncated = True
                item.content = f"[... Truncated due to total context budget of {char_budget} chars ...]"
                item.included_length = len(item.content)
                final_items.append(item)
                truncated_count += 1
                break

            if item_len > available:
                # Truncate individual item to fit remaining budget
                truncated_text = item.content[: available - 80] + "\n[... Source truncated by context compiler ...]"
                item.truncated = True
                item.included_length = len(truncated_text)
                item.content = truncated_text
                current_total_chars += len(truncated_text)
                final_items.append(item)
                truncated_count += 1
            else:
                current_total_chars += item_len
                final_items.append(item)

        provenance_index = {it.source_id: it for it in final_items}

        tier_counts = {}
        for it in final_items:
            t = it.epistemic_tier.value
            tier_counts[t] = tier_counts.get(t, 0) + 1

        diagnostics = {
            "agent_id": aid,
            "total_items": len(final_items),
            "tier_counts": tier_counts,
            "truncated_sources_count": truncated_count,
            "total_characters_included": current_total_chars,
            "char_budget": char_budget,
            "chat_id_scoped": ctx.chat_id,
            "business_id_scoped": ctx.business_id,
        }

        return GroundedContextPackage(
            objective=ctx.objective,
            agent_id=aid,
            evidence_items=final_items,
            provenance_index=provenance_index,
            diagnostics=diagnostics,
        )

    def compile_for_agent(
        self,
        agent_id: str,
        ctx: RuntimeContext,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
        query: str = "",
    ) -> AgentCompiledContext:
        """Legacy compatibility wrapper compiling AgentCompiledContext."""
        effective_ctx = ctx
        if (chat_id and ctx.chat_id != chat_id) or (project_id and ctx.project_id != project_id):
            effective_ctx = RuntimeContext(
                run_id=ctx.run_id,
                objective=ctx.objective,
                business_id=ctx.business_id,
                campaign_id=ctx.campaign_id,
                user_id=ctx.user_id,
                chat_id=chat_id or ctx.chat_id,
                project_id=project_id or ctx.project_id,
                current_stage=ctx.current_stage,
                status=ctx.status,
                knowledge_refs=list(ctx.knowledge_refs),
                memory_refs=list(ctx.memory_refs),
                execution_receipt_refs=list(ctx.execution_receipt_refs),
                artifact_refs=list(ctx.artifact_refs),
                approval_refs=list(ctx.approval_refs),
                working_state=dict(ctx.working_state),
                stage_outputs=dict(ctx.stage_outputs),
                unresolved_questions=list(ctx.unresolved_questions),
                constraints=list(ctx.constraints),
                risk_flags=list(ctx.risk_flags),
            )

        pkg = self.compile_grounded_package(agent_id, effective_ctx)
        session_chunks = [it.content for it in pkg.evidence_items if it.source_type == "SESSION_ATTACHMENT"]
        persistent_refs = [it.title_or_reference for it in pkg.evidence_items if it.source_type != "SESSION_ATTACHMENT" and it.epistemic_tier in (EpistemicTier.VERIFIED_SOURCE, EpistemicTier.UNVERIFIED_SOURCE)]
        memory_cits = [it.title_or_reference for it in pkg.evidence_items if it.source_type == "INSTITUTIONAL_MEMORY"]

        return AgentCompiledContext(
            agent_id=agent_id,
            objective=ctx.objective,
            session_knowledge_chunks=session_chunks,
            persistent_knowledge_refs=persistent_refs,
            memory_citations=memory_cits,
            constraints=ctx.constraints,
            raw_prompt_payload=pkg.render_prompt_section(),
        )
