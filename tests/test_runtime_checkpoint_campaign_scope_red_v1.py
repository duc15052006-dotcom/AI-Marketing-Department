from __future__ import annotations

import unittest

from runtime.context import RuntimeContext


class RuntimeCheckpointCampaignScopeRedV1Tests(unittest.TestCase):
    def _checkpoint(self, campaign_id: str):
        context = RuntimeContext(
            run_id="RUN-CHECKPOINT-CAMPAIGN-SCOPE-1",
            objective="Bind checkpoint integrity to authoritative campaign scope",
            business_id="BIZ-1",
            project_id="PROJ-1",
            chat_id="CHAT-1",
            campaign_id=campaign_id,
            user_id="USER-1",
        )
        return context.create_checkpoint()

    def test_checkpoint_captures_authoritative_campaign_scope(self) -> None:
        checkpoint = self._checkpoint("CAMP-A")
        self.assertEqual(
            "CAMP-A",
            getattr(checkpoint, "campaign_id", None),
            "ExecutionCheckpoint omitted authoritative campaign_id captured by RuntimeContext",
        )

    def test_campaign_scope_changes_checkpoint_integrity_digest(self) -> None:
        left = self._checkpoint("CAMP-A")
        right = self._checkpoint("CAMP-B")
        self.assertNotEqual(
            left.checkpoint_hash,
            right.checkpoint_hash,
            "otherwise-identical checkpoints from different campaign scopes share one integrity hash",
        )

    def test_identical_campaign_scope_remains_deterministic(self) -> None:
        left = self._checkpoint("CAMP-A")
        right = self._checkpoint("CAMP-A")
        self.assertEqual(left.checkpoint_hash, right.checkpoint_hash)


if __name__ == "__main__":
    unittest.main()
