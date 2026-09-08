"""Adversarial RED regressions for RuntimeContext model_copy scope authority.

Invariant: RuntimeContext.model_copy(update=...) must not create a copied context
that bypasses the authoritative scope immutability already enforced for direct
mutation. Plain/idempotent copies remain valid and must preserve runtime types.
"""

from __future__ import annotations

from datetime import datetime
import unittest

from runtime.context import ExecutionCheckpoint, RuntimeContext, RuntimeStage, RuntimeStatus


class RuntimeContextModelCopyScopeAuthorityV1Tests(unittest.TestCase):
    def _context(self) -> RuntimeContext:
        return RuntimeContext(
            run_id="RUN-CONTEXT-COPY-001",
            objective="Protect RuntimeContext copy authority",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            chat_id="CHAT-001",
            campaign_id="CAMPAIGN-001",
            user_id="USER-001",
        )

    def test_copy_cannot_rebind_authoritative_scope(self) -> None:
        ctx = self._context()
        attacks = {
            "run_id": "RUN-CONTEXT-COPY-OTHER",
            "business_id": "BIZ-OTHER",
            "project_id": "PROJECT-OTHER",
            "chat_id": "CHAT-OTHER",
            "campaign_id": "CAMPAIGN-OTHER",
            "user_id": "USER-OTHER",
        }
        for field_name, forged_value in attacks.items():
            with self.subTest(field=field_name):
                with self.assertRaises(AttributeError):
                    ctx.model_copy(update={field_name: forged_value})

    def test_plain_copy_preserves_scope_and_runtime_types(self) -> None:
        ctx = self._context()
        checkpoint = ctx.create_checkpoint()

        copied = ctx.model_copy()

        self.assertIsNot(copied, ctx)
        self.assertEqual(copied.scope, ctx.scope)
        self.assertIsInstance(copied.created_at, datetime)
        self.assertIsInstance(copied.current_stage, RuntimeStage)
        self.assertIsInstance(copied.status, RuntimeStatus)
        self.assertEqual(copied.created_at, ctx.created_at)
        self.assertEqual(copied.current_stage, ctx.current_stage)
        self.assertEqual(copied.status, ctx.status)
        self.assertEqual(len(copied.checkpoints), 1)
        self.assertIsInstance(copied.checkpoints[0], ExecutionCheckpoint)
        self.assertEqual(copied.checkpoints[0].checkpoint_id, checkpoint.checkpoint_id)

    def test_same_value_protected_updates_remain_idempotent(self) -> None:
        ctx = self._context()
        copied = ctx.model_copy(
            update={
                "run_id": ctx.run_id,
                "business_id": ctx.business_id,
                "project_id": ctx.project_id,
                "chat_id": ctx.chat_id,
                "campaign_id": ctx.campaign_id,
                "user_id": ctx.user_id,
            }
        )

        self.assertEqual(copied.scope, ctx.scope)
        self.assertIsInstance(copied.created_at, datetime)
        self.assertIsInstance(copied.current_stage, RuntimeStage)
        self.assertIsInstance(copied.status, RuntimeStatus)

    def test_deep_copy_preserves_types_without_aliasing_mutable_state(self) -> None:
        ctx = self._context()
        ctx.working_state["nested"] = {"items": ["original"]}
        ctx.create_checkpoint()

        copied = ctx.model_copy(deep=True)

        self.assertIsInstance(copied.created_at, datetime)
        self.assertIsInstance(copied.current_stage, RuntimeStage)
        self.assertIsInstance(copied.status, RuntimeStatus)
        self.assertIsInstance(copied.checkpoints[0], ExecutionCheckpoint)
        self.assertIsNot(copied.working_state, ctx.working_state)
        self.assertIsNot(copied.working_state["nested"], ctx.working_state["nested"])
        self.assertIsNot(copied.checkpoints, ctx.checkpoints)
        self.assertIsNot(copied.checkpoints[0], ctx.checkpoints[0])

        copied.working_state["nested"]["items"].append("copy-only")
        self.assertEqual(ctx.working_state["nested"]["items"], ["original"])


if __name__ == "__main__":
    unittest.main()
