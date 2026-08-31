"""Context Compiler for AI Marketing Department.

Assembles bounded, role-targeted grounded context packages for each of the Five Permanent Agents
from ephemeral session attachments, scoped persistent brand/project/global knowledge,
filtered institutional memories, and ToolGateway execution receipts.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from chat.knowledge import SessionKnowledgeStore
from governance.access_matrix import AgentAccessMatrix
from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import KnowledgeRepository, LocalKnowledgeRepository
from memory.models import MemoryItem, PromotionState
from memory.promotion import MemoryPromotionEngine
from memory.repository import LocalMemoryRepository, MemoryRepository
from runtime.context import EpistemicTier, EvidenceItem, GroundedContextPackage, RuntimeContext
from runtime.scope_bridge import RuntimeCanonicalScopePlan, build_runtime_canonical_scope_plan
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

    @staticmethod
    def _append_unique(values: List[str], value: Optional[str]) -> None:
        clean = str(value or "").strip()
        if clean and clean not in values:
            values.append(clean)

    @staticmethod
    def _legacy_alias_for_canonical_scope(scope_key: str) -> Optional[str]:
        """Return the exact legacy alias for one already-validated canonical key.

        This is a migration-only compatibility mapping.  It never accepts or
        creates wildcard scopes and it is derived only from the immutable
        RuntimeContext scope through :func:`build_runtime_canonical_scope_plan`.
        """

        prefix, sep, identifier = str(scope_key or "").partition(":")
        if not sep or not identifier:
            return None
        if prefix == "PROJECT":
            return f"SCOPE_PROJ_{identifier}"
        if prefix == "BUSINESS":
            return f"SCOPE_{identifier}"
        return None

    @classmethod
    def _build_dual_read_scopes(
        cls,
        exact_scope_keys: Sequence[str],
        *,
        include_global: bool,
        business_id: str,
    ) -> Tuple[str, ...]:
        """Build ordered canonical + legacy exact read scopes for migration.

        Ordering preserves the canonical authority contract: project before
        business, and GLOBAL only as the final fallback.  Each canonical scope
        is immediately followed by its exact legacy alias so old records remain
        readable while repositories are migrated.  ``SCOPE_BIZ_DEFAULT`` is a
        legacy alias for the historical default workspace only; it is never
        used for a real business tenant.
        """

        scopes: List[str] = []
        for canonical_scope in exact_scope_keys:
            cls._append_unique(scopes, canonical_scope)
            cls._append_unique(scopes, cls._legacy_alias_for_canonical_scope(canonical_scope))

        if include_global:
            cls._append_unique(scopes, "GLOBAL")
            if str(business_id or "").strip().upper() == "BIZ_DEFAULT":
                cls._append_unique(scopes, "SCOPE_BIZ_DEFAULT")
        return tuple(scopes)

    @classmethod
    def _scope_candidates_from_context(
        cls,
        ctx: RuntimeContext,
    ) -> Tuple[RuntimeCanonicalScopePlan, Tuple[str, ...], Tuple[str, ...]]:
        """Resolve all retrieval scopes exclusively from immutable runtime authority."""

        plan = build_runtime_canonical_scope_plan(ctx)
        knowledge_scopes = cls._build_dual_read_scopes(
            plan.knowledge_scope_keys,
            include_global=plan.include_global,
            business_id=plan.business_id,
        )
        memory_scopes = cls._build_dual_read_scopes(
            plan.memory_scope_keys,
            include_global=plan.include_global,
            business_id=plan.business_id,
        )
        return plan, knowledge_scopes, memory_scopes

    def _memory_repository_supports_exact_scope(self) -> bool:
        """Detect the new exact-scope repository interface without executing it."""

        try:
            parameters = inspect.signature(self.memory_repo.list_memories).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.name == "scope" or parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )

    def _list_memories_for_exact_scope(self, scope: str) -> List[MemoryItem]:
        """Read one exact scope from new or legacy MemoryRepository interfaces.

        ``ScopedMemoryRepository`` supports ``scope=`` directly.  The legacy
        repository interface does not, so its compatibility path performs an
        in-memory exact-scope filter immediately after the legacy list call.
        No item outside the requested exact scope is returned to the compiler.
        This fallback is intentionally temporary until backend repository
        composition is migrated in the next platform batch.

        Capability detection happens before execution so a real ``TypeError``
        raised inside a scoped repository is never mistaken for an old method
        signature and silently downgraded to the legacy compatibility path.
        """

        if self._memory_repository_supports_exact_scope():
            return list(self.memory_repo.list_memories(scope=scope))  # type: ignore[call-arg]
        return [
            memory
            for memory in self.memory_repo.list_memories()
            if str(getattr(memory, "scope", "GLOBAL") or "GLOBAL").strip() == scope
        ]

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

        scope_plan, knowledge_scopes, memory_scopes = self._scope_candidates_from_context(ctx)
        primary_evidence_scope = (
            scope_plan.knowledge_scope_keys[0]
            if scope_plan.knowledge_scope_keys
            else "GLOBAL"
        )

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
        # 2. Scoped Persistent Knowledge — canonical exact scopes + migration aliases
        # ---------------------------------------------------------------------
        if self.knowledge_repo:
            prof = AgentAccessMatrix.get_profile(aid)
            allowed_sources = prof.allowed_knowledge_sources if prof else []

            seen_knowledge_ids: set = set()
            for scope in knowledge_scopes:
                scoped_docs = self.knowledge_repo.list_documents(scope=scope)
                valid_docs = [
                    d
                    for d in scoped_docs
                    if d.source_type in allowed_sources and d.freshness != "RETIRED"
                ]
                for doc in valid_docs[:4]:
                    if doc.knowledge_id in seen_knowledge_ids:
                        continue
                    seen_knowledge_ids.add(doc.knowledge_id)
                    if doc.authority_level in (
                        AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                        AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                    ):
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
                            scope=doc.scope or scope,
                            title_or_reference=f"Knowledge Doc: {doc.title} (ID: {doc.knowledge_id}, Auth: {doc.authority_level.value})",
                            content=raw_text,
                            original_length=len(raw_text),
                            included_length=len(raw_text),
                            metadata={
                                "knowledge_id": doc.knowledge_id,
                                "version": doc.version,
                                "authority": doc.authority_level.value,
                                "retrieval_scope": scope,
                            },
                        )
                    )

        # ---------------------------------------------------------------------
        # 3. Institutional Memory — canonical exact scopes + migration aliases
        # ---------------------------------------------------------------------
        if self.memory_repo:
            prof = AgentAccessMatrix.get_profile(aid)
            allowed_types = prof.allowed_memory_types if prof else []
            min_conf = ctx.memory_policy.get("min_confidence", 0.60) if ctx.memory_policy else 0.60
            seen_memory_ids: set = set()

            for scope in memory_scopes:
                for m in self._list_memories_for_exact_scope(scope):
                    if m.memory_id in seen_memory_ids:
                        continue
                    if m.memory_type not in allowed_types:
                        continue
                    if m.confidence < min_conf:
                        continue
                    if MemoryPromotionEngine.audit_memory_staleness(m):
                        continue
                    seen_memory_ids.add(m.memory_id)

                    if m.promotion_level in (
                        PromotionState.VERIFIED_MEMORY,
                        PromotionState.PROMOTED_LEARNING,
                    ):
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
                            metadata={
                                "memory_id": m.memory_id,
                                "promotion_level": m.promotion_level.value,
                                "confidence": m.confidence,
                                "retrieval_scope": scope,
                            },
                        )
                    )

        # ---------------------------------------------------------------------
        # 4. ToolGateway Execution Results — Preserving REAL vs MOCK/SANDBOX & EvidenceRole
        # ---------------------------------------------------------------------
        if tool_receipts:
            for receipt in tool_receipts:
                if receipt.status != ExecutionStatus.SUCCESS:
                    continue

                mode = getattr(receipt, "execution_mode", ExecutionMode.MOCK)
                is_real = (mode == ExecutionMode.REAL or str(mode).upper() in ("REAL", "EXECUTIONMODE.REAL"))

                cap = self.capability_registry.get_capability(receipt.capability_id) if self.capability_registry else None
                evidence_role = getattr(cap, "evidence_role", EvidenceRole.NONE) if cap else EvidenceRole.NONE
                if isinstance(evidence_role, str):
                    try:
                        evidence_role = EvidenceRole(evidence_role.upper())
                    except ValueError:
                        evidence_role = EvidenceRole.NONE

                if evidence_role != EvidenceRole.OBSERVATION:
                    continue

                if is_real:
                    tier = EpistemicTier.SOURCE_BACKED_OBSERVATION
                    title_prefix = f"Live Tool Observation ({receipt.capability_id})"
                else:
                    tier = EpistemicTier.MOCK_OR_SANDBOX
                    title_prefix = f"Simulated Tool Output ({mode.value if hasattr(mode, 'value') else mode})"

                payload = receipt.output if receipt.output is not None else receipt.data
                if isinstance(payload, (dict, list)):
                    formatted_content = json.dumps(payload, indent=2, ensure_ascii=False)
                elif payload is not None:
                    formatted_content = str(payload)
                else:
                    formatted_content = "{}"

                res_hash = getattr(receipt, "result_hash", "") or (
                    receipt.calculate_result_hash()
                    if hasattr(receipt, "calculate_result_hash")
                    else ""
                )

                sid = f"TOOL-{run_prefix}-{item_counter:03d}"
                item_counter += 1
                evidence_items.append(
                    EvidenceItem(
                        source_id=sid,
                        epistemic_tier=tier,
                        source_type="TOOL_RECEIPT",
                        scope=primary_evidence_scope,
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
                item.truncated = True
                item.content = f"[... Truncated due to total context budget of {char_budget} chars ...]"
                item.included_length = len(item.content)
                final_items.append(item)
                truncated_count += 1
                break

            if item_len > available:
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
            "project_id_scoped": ctx.project_id,
            "canonical_knowledge_scopes": list(scope_plan.knowledge_scope_keys),
            "canonical_memory_scopes": list(scope_plan.memory_scope_keys),
            "knowledge_read_scopes": list(knowledge_scopes),
            "memory_read_scopes": list(memory_scopes),
            "global_fallback_enabled": scope_plan.include_global,
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
        session_chunks = [
            it.content for it in pkg.evidence_items if it.source_type == "SESSION_ATTACHMENT"
        ]
        persistent_refs = [
            it.title_or_reference
            for it in pkg.evidence_items
            if it.source_type != "SESSION_ATTACHMENT"
            and it.epistemic_tier in (
                EpistemicTier.VERIFIED_SOURCE,
                EpistemicTier.UNVERIFIED_SOURCE,
            )
        ]
        memory_cits = [
            it.title_or_reference
            for it in pkg.evidence_items
            if it.source_type == "INSTITUTIONAL_MEMORY"
        ]

        return AgentCompiledContext(
            agent_id=agent_id,
            objective=ctx.objective,
            session_knowledge_chunks=session_chunks,
            persistent_knowledge_refs=persistent_refs,
            memory_citations=memory_cits,
            constraints=ctx.constraints,
            raw_prompt_payload=pkg.render_prompt_section(),
        )
