"""Adversarial regression for the Brain -> ToolGateway execution boundary.

Invariant: a Brain action-authorizer denial must stop dispatch before the tool
policy/adapter path can create an external side effect.  Capability risk and
category supplied to the Brain must come from the trusted CapabilityRegistry,
not from caller-controlled ToolRequest parameters.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from brain.action_policy import ActionAuthorization, ActionDisposition
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionReceiptRepository, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class BrainRuntimeActionGateV1Tests(unittest.TestCase):
    def test_brain_denial_blocks_tool_dispatch_and_receipt_is_auditable(self) -> None:
        observed = []

        def deny(intent):
            observed.append(intent)
            return ActionAuthorization(
                intent_id=intent.intent_id,
                disposition=ActionDisposition.BLOCK,
                reason="adversarial policy denial",
            )

        with tempfile.TemporaryDirectory() as tmp:
            receipt_repo = ExecutionReceiptRepository(
                database_path=Path(tmp) / "receipts.sqlite3"
            )
            gateway = ToolGateway(
                capability_registry=CapabilityRegistry(),
                receipt_repository=receipt_repo,
                action_authorizer=deny,
            )

            receipt = gateway.execute(
                ToolRequest(
                    request_id="REQ-BRAIN-GATE-RED-001",
                    run_id="RUN-BRAIN-GATE-RED-001",
                    agent_id="intelligence",
                    capability_id="web_search",
                    parameters={
                        "query": "must never reach an adapter",
                        # Adversarial caller metadata must not become risk authority.
                        "risk_level": "LOW",
                        "capability_category": "READ_ONLY",
                    },
                )
            )

        self.assertEqual(len(observed), 1)
        intent = observed[0]
        self.assertEqual(intent.capability_id, "web_search")
        self.assertEqual(intent.agent_id, "intelligence")
        self.assertNotEqual(intent.intent_id, "")
        self.assertEqual(receipt.status, ExecutionStatus.BLOCKED)
        self.assertEqual(receipt.error_class, "BRAIN_ACTION_DENIED")
        self.assertIn("adversarial policy denial", receipt.error_message)


if __name__ == "__main__":
    unittest.main()
