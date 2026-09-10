"""Adversarial RED for canonical execution/ActionIntent -> Observation provenance.

Invariant: a canonical ObservationRecord carried out of ToolGateway must remain
causally attributable after it is detached from its ExecutionReceipt. The outer
ToolGateway, not an adapter/model payload, owns the binding to the actual
ExecutionReceipt.execution_id and canonical ActionIntent.intent_id. Legacy calls
must still bind execution provenance without fabricating Brain provenance.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict

from brain.action_policy import ActionAuthorization, ActionDisposition
from tests.test_brain_canonical_action_intent_tool_gateway_v1 import (
    BrainCanonicalActionIntentToolGatewayV1Tests as CanonicalGatewayContract,
)
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    RiskLevel,
)
from tools.observation.models import ObservationRecord
from tools.receipts import ExecutionReceiptRepository, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class ObservationProvenanceAdapter(BaseCapabilityAdapter):
    def __init__(self, *, forge_causal_provenance: bool = False) -> None:
        self.forge_causal_provenance = forge_causal_provenance
        self.call_count = 0

    @property
    def adapter_name(self) -> str:
        return "observation_provenance_adapter"

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
        self.call_count += 1
        obs = ObservationRecord(
            capability=capability_id,
            source_platform="web",
            source_type="search_discovery",
            source_url_or_id=parameters.get("query", "market evidence"),
            backend_used=self.adapter_name,
            collection_method="SEARCH_ENGINE_DISCOVERY",
            normalized_data={"results": [{"title": "bounded market evidence"}]},
            product_id="product-observation-provenance",
            brand_id="brand-observation-provenance",
            run_id=run_id,
            business_id=business_id,
            project_id=project_id,
        ).model_dump()
        if self.forge_causal_provenance:
            # Adapters are execution mechanisms, never authority sources.
            obs["execution_id"] = "EXEC-ADAPTER-FORGED"
            obs["action_intent_id"] = "AI-ADAPTER-FORGED"
        return AdapterResult(
            success=True,
            data={"result_count": 1},
            observation_record=obs,
        )


class BrainObservationActionIntentProvenanceV1Tests(unittest.TestCase):
    CAPABILITY_ID = "semantic_observation_provenance_test"

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "receipts.sqlite3"
        self.repo = ExecutionReceiptRepository(database_path=self.db_path)

    def tearDown(self) -> None:
        try:
            self.repo.close()
        except Exception:
            pass
        self._tmp.cleanup()

    @staticmethod
    def _structural_allow(intent):
        return ActionAuthorization(
            intent_id=intent.intent_id,
            disposition=ActionDisposition.ALLOW,
            reason="test structural allow after canonical semantic validation",
        )

    def _gateway(self, *, forge_causal_provenance: bool = False):
        registry = CapabilityRegistry()
        adapter = ObservationProvenanceAdapter(
            forge_causal_provenance=forge_causal_provenance
        )
        gateway = ToolGateway(
            capability_registry=registry,
            receipt_repository=self.repo,
            action_authorizer=self._structural_allow,
        )
        gateway.register_adapter(adapter)
        registry.register_capability(
            CapabilityDescriptor(
                capability_id=self.CAPABILITY_ID,
                name="Semantic observation provenance regression capability",
                category=CapabilityCategory.OBSERVE,
                description="Test-only observation capability for causal provenance.",
                provider=adapter.adapter_name,
                supported_agents=["content"],
                required_permissions=[],
                risk_level=RiskLevel.LOW,
                human_approval_required=False,
                retry_policy={
                    "max_retries": 0,
                    "backoff_seconds": 0.0,
                    "retryable_errors": [],
                },
                semantic_needs=["MARKET_RESEARCH"],
            )
        )
        return gateway, adapter

    @classmethod
    def _request(cls, run_id: str) -> ToolRequest:
        return ToolRequest(
            request_id=f"REQ-{run_id}",
            run_id=run_id,
            agent_id="content",
            capability_id=cls.CAPABILITY_ID,
            parameters={"query": "bounded market evidence"},
            business_id="business-observation-provenance",
            project_id="project-observation-provenance",
            brand_id="brand-observation-provenance",
        )

    def _execute_semantic(self, gateway: ToolGateway, run_id: str):
        return gateway.execute(
            self._request(run_id),
            action_intent=CanonicalGatewayContract._intent(),
            decision_request=CanonicalGatewayContract._decision_request(),
        )

    def test_observation_contract_exposes_causal_execution_fields(self) -> None:
        obs = ObservationRecord(
            capability=self.CAPABILITY_ID,
            source_url_or_id="market evidence",
            backend_used="test",
            normalized_data={},
            product_id="product-observation-provenance",
            brand_id="brand-observation-provenance",
        )
        payload = obs.model_dump()
        self.assertIn(
            "execution_id",
            payload,
            "STILL_PRESENT: canonical ObservationRecord has no execution provenance field.",
        )
        self.assertIn(
            "action_intent_id",
            payload,
            "STILL_PRESENT: canonical ObservationRecord has no Brain ActionIntent provenance field.",
        )

    def test_semantic_observation_binds_exact_receipt_and_action_intent_identity(self) -> None:
        gateway, adapter = self._gateway()
        receipt = self._execute_semantic(gateway, "RUN-OBS-PROV-001")

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        self.assertIsNotNone(receipt.observation_record)
        self.assertEqual("AI-GW-1", receipt.action_intent_id)
        self.assertEqual(
            receipt.execution_id,
            receipt.observation_record.get("execution_id"),
            "STILL_PRESENT: detached observation cannot prove which execution produced it.",
        )
        self.assertEqual(
            receipt.action_intent_id,
            receipt.observation_record.get("action_intent_id"),
            "STILL_PRESENT: detached observation loses canonical ActionIntent provenance.",
        )

    def test_legacy_observation_binds_execution_without_fabricating_brain_provenance(self) -> None:
        gateway, adapter = self._gateway()
        receipt = gateway.execute(self._request("RUN-OBS-PROV-002"))

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        self.assertIsNone(receipt.action_intent_id)
        self.assertEqual(
            receipt.execution_id,
            receipt.observation_record.get("execution_id"),
            "STILL_PRESENT: legacy observation is not bound to its actual execution receipt.",
        )
        self.assertIsNone(
            receipt.observation_record.get("action_intent_id"),
            "REGRESSION: legacy execution must not fabricate canonical Brain provenance.",
        )

    def test_adapter_cannot_self_attest_foreign_causal_identity(self) -> None:
        gateway, adapter = self._gateway(forge_causal_provenance=True)
        receipt = self._execute_semantic(gateway, "RUN-OBS-PROV-003")

        self.assertEqual(ExecutionStatus.SUCCESS, receipt.status)
        self.assertEqual(1, adapter.call_count)
        self.assertNotEqual("EXEC-ADAPTER-FORGED", receipt.observation_record.get("execution_id"))
        self.assertNotEqual("AI-ADAPTER-FORGED", receipt.observation_record.get("action_intent_id"))
        self.assertEqual(receipt.execution_id, receipt.observation_record.get("execution_id"))
        self.assertEqual("AI-GW-1", receipt.observation_record.get("action_intent_id"))

    def test_sqlite_restart_preserves_observation_causal_provenance(self) -> None:
        gateway, _ = self._gateway()
        receipt = self._execute_semantic(gateway, "RUN-OBS-PROV-004")
        execution_id = receipt.execution_id
        self.repo.close()

        reopened = ExecutionReceiptRepository(database_path=self.db_path)
        try:
            loaded = reopened.get_receipt(execution_id)
            self.assertIsNotNone(loaded)
            self.assertIsNotNone(loaded.observation_record)
            detached = ObservationRecord(**loaded.observation_record)
            payload = detached.model_dump()
            self.assertEqual(
                execution_id,
                payload.get("execution_id"),
                "STILL_PRESENT: restart loses Observation -> ExecutionReceipt provenance.",
            )
            self.assertEqual(
                "AI-GW-1",
                payload.get("action_intent_id"),
                "STILL_PRESENT: restart loses Observation -> ActionIntent provenance.",
            )
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
