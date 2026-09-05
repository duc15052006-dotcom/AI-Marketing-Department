"""Adversarial regression for durable Memory Manager secret persistence."""

from __future__ import annotations

import unittest

from memory.lifecycle_models import MemoryScope
from memory.manager import MemoryManager
from memory.models import MemoryType


class MemoryPersistenceSecretSanitizationV1Tests(unittest.TestCase):
    def test_remember_does_not_persist_secrets_in_content_context_or_metadata(self) -> None:
        manager = MemoryManager()
        context = {
            "api_key": "context-secret-key-123456",
            "nested": {
                "message": "password=context-password-123456",
                "safe": "keep-context",
            },
        }
        metadata = {
            "client_secret": "metadata-client-secret-123456",
            "note": "Authorization: Bearer metadata-token-123456",
            "safe_meta": "keep-metadata",
        }

        created = manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content=(
                "Provider diagnostic Authorization: Bearer content-token-123456 "
                "api_key=content-api-key-123456"
            ),
            scope=MemoryScope(project_id="SECRET-TEST"),
            context=context,
            metadata=metadata,
        )

        self.assertTrue(created.success)
        stored = manager.repository.get_memory(created.memory_id or "")
        self.assertIsNotNone(stored)
        assert stored is not None

        self.assertNotIn("content-token-123456", stored.content)
        self.assertNotIn("content-api-key-123456", stored.content)
        self.assertIn("[REDACTED", stored.content)

        self.assertEqual(stored.context["api_key"], "[REDACTED_SECRET]")
        self.assertNotIn("context-password-123456", stored.context["nested"]["message"])
        self.assertEqual(stored.context["nested"]["safe"], "keep-context")

        self.assertEqual(stored.metadata["client_secret"], "[REDACTED_SECRET]")
        self.assertNotIn("metadata-token-123456", stored.metadata["note"])
        self.assertEqual(stored.metadata["safe_meta"], "keep-metadata")

        # Sanitization must happen on defensive copies, not mutate caller-owned payloads.
        self.assertEqual(context["api_key"], "context-secret-key-123456")
        self.assertEqual(metadata["client_secret"], "metadata-client-secret-123456")

    def test_benign_memory_payload_is_preserved(self) -> None:
        manager = MemoryManager()
        content = "Decor campaign improved conversion after stronger product proof."
        context = {"channel": "social", "audience": "decor"}
        metadata = {"experiment": "creative-proof", "note": "validated observation"}

        created = manager.remember(
            memory_type=MemoryType.SUCCESS_FAILURE_MEMORY,
            agent_source="performance",
            content=content,
            scope=MemoryScope(project_id="BENIGN-TEST"),
            context=context,
            metadata=metadata,
        )

        self.assertTrue(created.success)
        stored = manager.repository.get_memory(created.memory_id or "")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.content, content)
        self.assertEqual(stored.context, context)
        self.assertEqual(stored.metadata["experiment"], metadata["experiment"])
        self.assertEqual(stored.metadata["note"], metadata["note"])


if __name__ == "__main__":
    unittest.main()
