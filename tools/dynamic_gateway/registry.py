"""Composite capability registry for built-in and runtime-discovered tools.

The base CapabilityRegistry remains authoritative for built-in capabilities.
Dynamic sources (plugins, MCP servers, future connectors) are stored in an
overlay that can be atomically replaced per source without mutating the base
registry or leaving stale capabilities behind.
"""

from __future__ import annotations

import copy
from typing import Dict, Iterable, List, Optional, Set

from tools.capabilities import CapabilityCategory, CapabilityDescriptor, CapabilityRegistry


class DynamicCapabilityCollisionError(RuntimeError):
    """Raised when two capability authorities claim the same capability ID."""


class CompositeCapabilityRegistry:
    """Read-compatible CapabilityRegistry overlay with per-source lifecycle."""

    def __init__(self, base_registry: Optional[CapabilityRegistry] = None) -> None:
        self.base_registry = base_registry or CapabilityRegistry()
        self._dynamic: Dict[str, CapabilityDescriptor] = {}
        self._source_index: Dict[str, Set[str]] = {}
        self._capability_source: Dict[str, str] = {}

    @staticmethod
    def _normalize_capability_id(capability_id: str) -> str:
        return (capability_id or "").strip().lower()

    @staticmethod
    def _normalize_source(source: str) -> str:
        normalized = (source or "").strip().lower()
        if not normalized:
            raise ValueError("dynamic capability source is required")
        return normalized

    def replace_dynamic_source(
        self,
        source: str,
        descriptors: Iterable[CapabilityDescriptor],
    ) -> int:
        """Atomically replace all capabilities exported by one dynamic source.

        Validation is completed before current source entries are removed, so a
        bad refresh cannot partially corrupt the active registry.
        """
        source_key = self._normalize_source(source)
        staged: Dict[str, CapabilityDescriptor] = {}

        for descriptor in descriptors:
            capability_id = self._normalize_capability_id(descriptor.capability_id)
            if not capability_id:
                raise ValueError("dynamic capability_id cannot be empty")
            if capability_id in staged:
                raise DynamicCapabilityCollisionError(
                    f"source '{source_key}' exported duplicate capability '{capability_id}'"
                )

            base_descriptor = self.base_registry.get_capability(capability_id)
            if base_descriptor is not None:
                raise DynamicCapabilityCollisionError(
                    f"dynamic capability '{capability_id}' collides with built-in capability"
                )

            existing_source = self._capability_source.get(capability_id)
            if existing_source is not None and existing_source != source_key:
                raise DynamicCapabilityCollisionError(
                    f"dynamic capability '{capability_id}' already belongs to source '{existing_source}'"
                )

            cloned = copy.deepcopy(descriptor)
            cloned.capability_id = capability_id
            staged[capability_id] = cloned

        old_ids = set(self._source_index.get(source_key, set()))
        for capability_id in old_ids:
            self._dynamic.pop(capability_id, None)
            self._capability_source.pop(capability_id, None)

        new_ids = set(staged)
        for capability_id, descriptor in staged.items():
            self._dynamic[capability_id] = descriptor
            self._capability_source[capability_id] = source_key
        self._source_index[source_key] = new_ids
        return len(new_ids)

    def remove_dynamic_source(self, source: str) -> int:
        source_key = self._normalize_source(source)
        removed = set(self._source_index.pop(source_key, set()))
        for capability_id in removed:
            self._dynamic.pop(capability_id, None)
            self._capability_source.pop(capability_id, None)
        return len(removed)

    def get_capability(self, capability_id: str) -> Optional[CapabilityDescriptor]:
        capability_key = self._normalize_capability_id(capability_id)
        dynamic = self._dynamic.get(capability_key)
        if dynamic is not None:
            return copy.deepcopy(dynamic)
        base = self.base_registry.get_capability(capability_key)
        return copy.deepcopy(base) if base is not None else None

    def list_capabilities(
        self,
        category: Optional[CapabilityCategory] = None,
    ) -> List[CapabilityDescriptor]:
        base = self.base_registry.list_capabilities(category=category)
        dynamic = list(self._dynamic.values())
        if category is not None:
            dynamic = [descriptor for descriptor in dynamic if descriptor.category == category]
        combined = [copy.deepcopy(item) for item in base] + [copy.deepcopy(item) for item in dynamic]
        return sorted(combined, key=lambda item: item.capability_id)

    def list_capabilities_for_agent(self, agent_id: str) -> List[CapabilityDescriptor]:
        aid = (agent_id or "").strip().lower()
        result: List[CapabilityDescriptor] = []
        for descriptor in self.list_capabilities():
            supported = {str(value).lower() for value in descriptor.supported_agents}
            if not supported or "all" in supported or aid in supported:
                result.append(descriptor)
        return result

    def list_dynamic_sources(self) -> List[str]:
        return sorted(self._source_index)

    def list_dynamic_capability_ids(self, source: Optional[str] = None) -> List[str]:
        if source is None:
            return sorted(self._dynamic)
        source_key = self._normalize_source(source)
        return sorted(self._source_index.get(source_key, set()))

    def source_for(self, capability_id: str) -> Optional[str]:
        return self._capability_source.get(self._normalize_capability_id(capability_id))

    def snapshot(self) -> Dict[str, object]:
        return {
            "built_in_count": len(self.base_registry.list_capabilities()),
            "dynamic_count": len(self._dynamic),
            "dynamic_sources": {
                source: sorted(capability_ids)
                for source, capability_ids in sorted(self._source_index.items())
            },
        }
