from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionReceiptRepository, ExecutionStatus
from tools.security import PolicyEngine
from tools.tool_gateway import ToolGateway, ToolRequest


class AmbiguousThenSuccessPublishingAdapter(BaseCapabilityAdapter):
    """First dispatch becomes externally ambiguous; any second dispatch is a duplicate."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def adapter_name(self) -> str:
        return "social_publish_adapter"

    def execution_mode_for(self, _capability_id: str) -> ExecutionMode:
        return ExecutionMode.SANDBOX

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 30.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError(
                "SIMULATED_CONNECTION_LOSS_AFTER_REMOTE_ACCEPTANCE"
            )
        return AdapterResult(
            success=True,
            data={"publication_id": "DUPLICATE-DISPATCH"},
            execution_mode=ExecutionMode.SANDBOX,
        )


class RuntimeConsequentialRequestIdempotencyV1Tests(unittest.TestCase):
    def _gateway(
        self,
        repo: ExecutionReceiptRepository,
        policy: PolicyEngine,
        adapter: AmbiguousThenSuccessPublishingAdapter,
    ) -> ToolGateway:
        gateway = ToolGateway(
            capability_registry=CapabilityRegistry(),
            policy_engine=policy,
            receipt_repository=repo,
        )
        gateway.register_adapter(adapter, aliases=["social_publish_adapter"])
        return gateway

    @staticmethod
    def _approval(policy: PolicyEngine, *, run_id: str, business_id: str, parameters: Dict[str, Any]) -> str:
        return policy.create_server_approval(
            capability_id="social_publishing",
            parameters=parameters,
            run_id=run_id,
            business_id=business_id,
            approved_by="Idempotency Regression Test",
        ).approval_token

    def test_restart_retry_of_same_ambiguous_request_id_never_redispatches(self) -> None:
        run_id = "RUN-IDEMPOTENCY-1"
        request_id = "REQ-IDEMPOTENCY-1"
        business_id = "BIZ-IDEMPOTENCY-1"
        parameters = {"platform": "linkedin", "content": "single external effect"}
        adapter = AmbiguousThenSuccessPublishingAdapter()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "effect-journal.sqlite3"

            first_repo = ExecutionReceiptRepository(database_path=db_path)
            try:
                first_policy = PolicyEngine()
                first_gateway = self._gateway(first_repo, first_policy, adapter)
                first_receipt = first_gateway.execute(
                    ToolRequest(
                        request_id=request_id,
                        run_id=run_id,
                        agent_id="cmo",
                        capability_id="social_publishing",
                        parameters=parameters,
                        approval_token=self._approval(
                            first_policy,
                            run_id=run_id,
                            business_id=business_id,
                            parameters=parameters,
                        ),
                        business_id=business_id,
                    )
                )

                self.assertEqual(1, adapter.calls)
                self.assertEqual(ExecutionStatus.ERROR, first_receipt.status)
                self.assertEqual(
                    "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME",
                    first_receipt.error_class,
                )
            finally:
                first_repo.close()

            # Simulate a fresh process with a fresh in-memory approval authority,
            # but the same durable external-effect journal.
            restarted_repo = ExecutionReceiptRepository(database_path=db_path)
            try:
                restarted_repo.reconcile_unfinished_intents()
                restarted_policy = PolicyEngine()
                restarted_gateway = self._gateway(
                    restarted_repo, restarted_policy, adapter
                )

                replay_receipt = restarted_gateway.execute(
                    ToolRequest(
                        request_id=request_id,
                        run_id=run_id,
                        agent_id="cmo",
                        capability_id="social_publishing",
                        parameters=parameters,
                        approval_token=self._approval(
                            restarted_policy,
                            run_id=run_id,
                            business_id=business_id,
                            parameters=parameters,
                        ),
                        business_id=business_id,
                    )
                )

                self.assertEqual(
                    1,
                    adapter.calls,
                    "CONSEQUENTIAL_REQUEST_REPLAYED: same durable request_id dispatched the provider twice after an ambiguous external outcome",
                )
                self.assertNotEqual(ExecutionStatus.SUCCESS, replay_receipt.status)
                self.assertEqual(
                    "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME",
                    replay_receipt.error_class,
                )
                self.assertEqual(
                    first_receipt.execution_id,
                    replay_receipt.execution_id,
                    "IDEMPOTENT_RETRY_DID_NOT_REUSE_DURABLE_RESULT: a replay of the same request_id must return the existing settled evidence",
                )

                matching_intents = [
                    intent
                    for intent in restarted_repo.list_execution_intents_for_run(run_id)
                    if intent.request_id == request_id
                ]
                self.assertEqual(
                    1,
                    len(matching_intents),
                    "DUPLICATE_DURABLE_INTENT: same consequential request_id created multiple intent records",
                )
            finally:
                restarted_repo.close()


if __name__ == "__main__":
    unittest.main()
