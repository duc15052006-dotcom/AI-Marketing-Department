"""Adversarial RED for canonical Brain ActionIntent -> ExecutionReceipt provenance.

Invariant: once ToolGateway has validated canonical semantic ActionIntent authority
and actually dispatches a capability, the resulting immutable ExecutionReceipt
must carry the exact canonical ActionIntent identity. SQLite round-trips must
preserve it, legacy no-semantic executions must remain explicitly unbound, and
the provenance field must participate in receipt immutability.

This slice deliberately does not add ActionIntent provenance to the separate
pre-dispatch ExecutionIntent journal; that requires its own durable schema
migration and remains a separate hardening boundary.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brain.action_policy import ActionAuthorization, ActionDisposition
from tests.test_brain_canonical_action_intent_tool_gateway_v1 import (
    BrainCanonicalActionIntentToolGatewayV1Tests as CanonicalGatewayContract,
)
from tools.capabilities import CapabilityRegistry
from tools.receipts import (
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreConflictError,
)
from tools.tool_gateway import ToolGateway


class BrainActionIntentReceiptProvenanceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = ExecutionReceiptRepository(
            database_path=Path(self._tmp.name) / "receipts.sqlite3"
        )

    def tearDown(self) -> None:
        self.repo.close()
        self._tmp.cleanup()

    def _gateway(self) -> ToolGateway:
        def allow_structural(intent):
            return ActionAuthorization(
                intent_id=intent.intent_id,
                disposition=ActionDisposition.ALLOW,
                reason="test structural allow after canonical semantic validation",
            )

        return ToolGateway(
            capability_registry=CapabilityRegistry(),
            receipt_repository=self.repo,
            action_authorizer=allow_structural,
        )

    def test_dispatched_receipt_carries_exact_canonical_action_intent_id(self) -> None:
        receipt = self._gateway().execute(
            CanonicalGatewayContract._request(),
            action_intent=CanonicalGatewayContract._intent(),
            decision_request=CanonicalGatewayContract._decision_request(),
        )
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(
            "AI-GW-1",
            getattr(receipt, "action_intent_id", None),
            "STILL_PRESENT: dispatched receipt loses canonical Brain ActionIntent provenance.",
        )

    def test_sqlite_round_trip_preserves_canonical_action_intent_id(self) -> None:
        receipt = self._gateway().execute(
            CanonicalGatewayContract._request(),
            action_intent=CanonicalGatewayContract._intent(),
            decision_request=CanonicalGatewayContract._decision_request(),
        )
        persisted = self.repo.get_receipt(receipt.execution_id)
        self.assertIsNotNone(persisted)
        self.assertEqual(
            "AI-GW-1",
            getattr(persisted, "action_intent_id", None),
            "STILL_PRESENT: durable receipt round-trip loses canonical ActionIntent provenance.",
        )

    def test_legacy_execution_remains_explicitly_unbound(self) -> None:
        receipt = self._gateway().execute(CanonicalGatewayContract._request())
        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertIsNone(
            getattr(receipt, "action_intent_id", None),
            "Legacy execution must not fabricate semantic Brain provenance.",
        )

    def test_unvalidated_semantic_context_cannot_stamp_receipt_provenance(self) -> None:
        receipt = self._gateway().execute(
            CanonicalGatewayContract._request(),
            action_intent=CanonicalGatewayContract._intent(),
        )
        self.assertEqual(ExecutionStatus.BLOCKED, receipt.status)
        self.assertIsNone(
            getattr(receipt, "action_intent_id", None),
            "Incomplete semantic context must not self-declare canonical provenance.",
        )

    def test_action_intent_provenance_participates_in_receipt_immutability(self) -> None:
        original = ExecutionReceipt(
            run_id="RUN-PROV-1",
            agent_id="content",
            capability_id="web_search",
            provider="search_adapter",
            request_hash="a" * 64,
            status=ExecutionStatus.SUCCESS,
            data={"ok": True},
            action_intent_id="AI-PROV-A",
        )
        stored = self.repo.save_receipt(original)
        conflicting_payload = stored.model_dump()
        conflicting_payload["action_intent_id"] = "AI-PROV-B"
        conflicting = ExecutionReceipt(**conflicting_payload)

        with self.assertRaises(
            ReceiptStoreConflictError,
            msg="STILL_PRESENT: canonical ActionIntent provenance is outside receipt immutability.",
        ):
            self.repo.save_receipt(conflicting)


if __name__ == "__main__":
    unittest.main()
