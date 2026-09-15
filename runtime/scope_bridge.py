"""Canonical scope planning bridge for governed Knowledge/Memory integration.

This module translates the immutable :class:`RuntimeContext.scope` authority
into ordered canonical scope keys understood by the governed Knowledge and
Memory repositories.  It intentionally performs no repository reads/writes and
never trusts mutable ``working_state`` scope hints.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Type

from knowledge.lifecycle_models import KnowledgeScope
from memory.lifecycle_models import MemoryScope
from runtime.context import AuthoritativeScope, RuntimeContext


_DEFAULT_BUSINESS_SCOPE_IDS = frozenset({"", "GLOBAL", "BIZ_DEFAULT"})
_GLOBAL_PROJECT_SENTINELS = frozenset({"", "GLOBAL"})


@dataclass(frozen=True)
class RuntimeCanonicalScopePlan:
    """Immutable exact-scope retrieval plan derived from runtime authority.

    Exact keys are ordered from the most specific currently-supported runtime
    scope to the broader tenant scope.  ``GLOBAL`` is represented separately by
    ``include_global`` so callers cannot accidentally treat it as an exact
    private scope.

    Campaign/brand/product scoping is deliberately not invented here.  Runtime
    v1 has authoritative business/project IDs, while persisted project data is
    project-only today.  Later integrations can extend this contract only after
    their write-side scope binding is explicit and regression-tested.
    """

    run_id: str
    business_id: str
    project_id: str
    campaign_id: str
    knowledge_scope_keys: Tuple[str, ...]
    memory_scope_keys: Tuple[str, ...]
    include_global: bool = True


def _clean(value: object) -> str:
    return str(value or "").strip()


def _canonical_pair(*, business_id: str = "", project_id: str = "") -> Tuple[str, str]:
    """Build and cross-check Knowledge/Memory canonical keys for one exact scope."""

    knowledge_key = KnowledgeScope(
        business_id=business_id,
        project_id=project_id,
    ).canonical_key()
    memory_key = MemoryScope(
        business_id=business_id,
        project_id=project_id,
    ).canonical_key()
    if knowledge_key != memory_key:
        raise ValueError(
            "KNOWLEDGE_MEMORY_SCOPE_SCHEMA_DIVERGENCE: canonical scope models disagree"
        )
    return knowledge_key, memory_key


def build_runtime_canonical_scope_plan(context: RuntimeContext) -> RuntimeCanonicalScopePlan:
    """Derive exact governed scope keys exclusively from immutable runtime scope.

    Current migration semantics intentionally mirror the persisted workspace
    boundaries that already exist in the product:

    * a project is an exact project-only scope (``PROJECT:<id>``),
    * a real business is a separate exact business scope (``BUSINESS:<id>``),
    * project scope is queried before business scope,
    * ``BIZ_DEFAULT``/``GLOBAL`` do not create a private business scope,
    * ``GLOBAL`` is an explicit fallback flag, never a wildcard lookup.

    Mutable ``working_state['knowledge_scope']`` / ``['memory_scope']`` values
    are deliberately ignored.
    """

    authority: AuthoritativeScope = context.scope
    business_id = _clean(authority.business_id)
    project_id = _clean(authority.project_id)
    campaign_id = _clean(authority.campaign_id)
    trusted_knowledge_scope = _clean(authority.trusted_knowledge_scope)
    trusted_memory_scope = _clean(authority.trusted_memory_scope)

    knowledge_keys = []
    memory_keys = []

    if project_id.upper() not in _GLOBAL_PROJECT_SENTINELS:
        knowledge_key, memory_key = _canonical_pair(project_id=project_id)
        knowledge_keys.append(knowledge_key)
        memory_keys.append(memory_key)

    if business_id.upper() not in _DEFAULT_BUSINESS_SCOPE_IDS:
        knowledge_key, memory_key = _canonical_pair(business_id=business_id)
        if knowledge_key not in knowledge_keys:
            knowledge_keys.append(knowledge_key)
        if memory_key not in memory_keys:
            memory_keys.append(memory_key)

    # Exact legacy aliases are accepted only after a trusted workspace binds
    # them into immutable RuntimeContext authority at run creation.
    if trusted_knowledge_scope and trusted_knowledge_scope.upper() != "GLOBAL":
        if trusted_knowledge_scope not in knowledge_keys:
            knowledge_keys.append(trusted_knowledge_scope)
    if trusted_memory_scope and trusted_memory_scope.upper() != "GLOBAL":
        if trusted_memory_scope not in memory_keys:
            memory_keys.append(trusted_memory_scope)

    return RuntimeCanonicalScopePlan(
        run_id=authority.run_id,
        business_id=business_id,
        project_id=project_id,
        campaign_id=campaign_id,
        knowledge_scope_keys=tuple(knowledge_keys),
        memory_scope_keys=tuple(memory_keys),
        include_global=True,
    )
