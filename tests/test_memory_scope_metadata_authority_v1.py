from __future__ import annotations

import unittest

from memory.lifecycle_models import MemoryScope
from memory.manager import MemoryManager
from memory.models import MemoryType


class MemoryScopeMetadataAuthorityV1Tests(unittest.TestCase):
    def test_caller_cannot_override_persisted_scope_key_metadata(self) -> None:
        manager = MemoryManager()
        scope = MemoryScope(business_id="BIZ_A", project_id="PROJ_A")
        expected_scope = scope.canonical_key()

        result = manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Keep the validated project-level positioning decision.",
            scope=scope,
            metadata={
                "scope_key": "GLOBAL",
                "note": "caller metadata should remain otherwise intact",
            },
        )

        self.assertTrue(result.success)
        self.assertIsNotNone(result.memory_id)
        stored = manager.repository.get_memory(result.memory_id or "")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.scope, expected_scope)
        self.assertEqual(stored.metadata.get("scope_key"), expected_scope)
        self.assertEqual(stored.metadata.get("note"), "caller metadata should remain otherwise intact")

    def test_benign_metadata_is_preserved_with_authoritative_scope_key(self) -> None:
        manager = MemoryManager()
        scope = MemoryScope(business_id="BIZ_SAFE", project_id="PROJ_SAFE")
        expected_scope = scope.canonical_key()

        result = manager.remember(
            memory_type=MemoryType.EPISODIC_MEMORY,
            agent_source="performance",
            content="Campaign observation retained for later governed review.",
            scope=scope,
            metadata={"channel": "paid_social", "iteration": 3},
        )

        self.assertTrue(result.success)
        stored = manager.repository.get_memory(result.memory_id or "")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.metadata.get("scope_key"), expected_scope)
        self.assertEqual(stored.metadata.get("channel"), "paid_social")
        self.assertEqual(stored.metadata.get("iteration"), 3)


if __name__ == "__main__":
    unittest.main()
