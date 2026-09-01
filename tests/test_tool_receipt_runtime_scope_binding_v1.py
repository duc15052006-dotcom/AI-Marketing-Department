"""Adversarial regression for ToolGateway receipt/runtime scope binding.

A GroundedContextPackage is a model-input authority boundary. Observation
receipts from a different run/workspace must never become evidence merely
because a caller supplied them to ContextCompiler.
"""

from __future__ import annotations

import unittest

from runtime.context import RuntimeContext
from runtime.context_compiler import ContextCompiler
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionStatus


class ToolReceiptRuntimeScopeBindingV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = ContextCompiler(capability_registry=CapabilityRegistry())
        self.ctx = RuntimeContext(
            run_id="RUN-SCOPE-A",
            objective="Audit current campaign performance",
            business_id="BIZ_A",
            project_id="PROJ_A",
            chat_id="CHAT_A",
        )

    @staticmethod
    def _receipt(
        *,
        run_id: str = "RUN-SCOPE-A",
        business_id: str = "BIZ_A",
        project_id: str = "PROJ_A",
        chat_id: str = "CHAT_A",
        marker: str,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id=f"EXEC-{marker}",
            run_id=run_id,
            agent_id="cmo",
            capability_id="analytics_retrieval",
            provider="analytics_adapter",
            request_hash=f"HASH-{marker}",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            business_id=business_id,
            project_id=project_id,
            chat_id=chat_id,
            data={"marker": marker},
        )

    @staticmethod
    def _receipt_ids(package) -> set[str]:
        return {
            str(item.metadata.get("receipt_id"))
            for item in package.evidence_items
            if item.source_type == "TOOL_RECEIPT"
        }

    def test_foreign_runtime_scope_receipts_are_rejected(self) -> None:
        cases = (
            self._receipt(run_id="RUN-SCOPE-B", marker="FOREIGN-RUN"),
            self._receipt(business_id="BIZ_B", marker="FOREIGN-BUSINESS"),
            self._receipt(project_id="PROJ_B", marker="FOREIGN-PROJECT"),
            self._receipt(chat_id="CHAT_B", marker="FOREIGN-CHAT"),
        )

        for receipt in cases:
            with self.subTest(execution_id=receipt.execution_id):
                package = self.compiler.compile_grounded_package(
                    "cmo",
                    self.ctx,
                    tool_receipts=[receipt],
                )
                self.assertNotIn(receipt.execution_id, self._receipt_ids(package))

    def test_same_runtime_scope_observation_receipt_remains_grounded(self) -> None:
        receipt = self._receipt(marker="SAME-SCOPE")
        package = self.compiler.compile_grounded_package(
            "cmo",
            self.ctx,
            tool_receipts=[receipt],
        )
        self.assertIn(receipt.execution_id, self._receipt_ids(package))


if __name__ == "__main__":
    unittest.main()
