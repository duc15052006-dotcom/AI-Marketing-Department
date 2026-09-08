from __future__ import annotations

import unittest

from runtime.context import RuntimeContext


class RuntimeCheckpointUserScopeRedV1Tests(unittest.TestCase):
    def _checkpoint(self, user_id: str):
        context = RuntimeContext(
            run_id="RUN-CHECKPOINT-USER-SCOPE-1",
            objective="Bind checkpoint integrity to authoritative user scope",
            business_id="BIZ-1",
            project_id="PROJ-1",
            chat_id="CHAT-1",
            campaign_id="CAMP-1",
            user_id=user_id,
        )
        return context.create_checkpoint()

    def test_checkpoint_captures_authoritative_user_scope(self) -> None:
        checkpoint = self._checkpoint("USER-A")
        self.assertEqual(
            "USER-A",
            getattr(checkpoint, "user_id", None),
            "ExecutionCheckpoint omitted authoritative user_id captured by RuntimeContext",
        )

    def test_user_scope_changes_checkpoint_integrity_digest(self) -> None:
        left = self._checkpoint("USER-A")
        right = self._checkpoint("USER-B")
        self.assertNotEqual(
            left.checkpoint_hash,
            right.checkpoint_hash,
            "otherwise-identical checkpoints from different user scopes share one integrity hash",
        )

    def test_identical_user_scope_remains_deterministic(self) -> None:
        left = self._checkpoint("USER-A")
        right = self._checkpoint("USER-A")
        self.assertEqual(left.checkpoint_hash, right.checkpoint_hash)


if __name__ == "__main__":
    unittest.main()
