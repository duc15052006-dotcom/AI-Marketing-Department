from __future__ import annotations

import unittest

from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    EvidenceRole,
    PermissionLevel,
    RiskLevel,
)
from tools.receipts import ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


class CapabilityRegistryPolicyImmutabilityAdversarialV1Tests(unittest.TestCase):
    @staticmethod
    def _critical_publish_descriptor(capability_id: str) -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=capability_id,
            name="Critical Publish Mutability Probe",
            category=CapabilityCategory.PUBLISH,
            evidence_role=EvidenceRole.ACTION,
            description="Adversarial capability used to prove registry policy is snapshot authority.",
            required_permissions=[PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE],
            risk_level=RiskLevel.CRITICAL,
            human_approval_required=True,
            supported_agents=["cmo"],
            provider="social_publish_adapter",
            timeout_policy=30.0,
            retry_policy={
                "max_retries": 0,
                "backoff_seconds": 0.0,
                "retryable_errors": [],
            },
            audit_policy={
                "log_payload": True,
                "redact_secrets": True,
                "emit_receipt": True,
            },
        )

    @staticmethod
    def _downgrade(descriptor: CapabilityDescriptor) -> None:
        descriptor.category = CapabilityCategory.OBSERVE
        descriptor.evidence_role = EvidenceRole.OBSERVATION
        descriptor.required_permissions = [PermissionLevel.READ_ONLY]
        descriptor.risk_level = RiskLevel.LOW
        descriptor.human_approval_required = False
        descriptor.supported_agents = ["all"]
        descriptor.retry_policy["max_retries"] = 99
        descriptor.audit_policy["redact_secrets"] = False

    def _assert_policy_still_authoritative(
        self,
        registry: CapabilityRegistry,
        capability_id: str,
    ) -> None:
        current = registry.get_capability(capability_id)
        self.assertIsNotNone(current)
        assert current is not None
        self.assertEqual(CapabilityCategory.PUBLISH, current.category)
        self.assertEqual(EvidenceRole.ACTION, current.evidence_role)
        self.assertEqual(
            [PermissionLevel.PUBLISH, PermissionLevel.EXTERNAL_WRITE],
            current.required_permissions,
        )
        self.assertEqual(RiskLevel.CRITICAL, current.risk_level)
        self.assertTrue(current.human_approval_required)
        self.assertEqual(["cmo"], current.supported_agents)
        self.assertEqual(0, current.retry_policy["max_retries"])
        self.assertTrue(current.audit_policy["redact_secrets"])

        gateway = ToolGateway(capability_registry=registry)
        receipt = gateway.execute(
            ToolRequest(
                run_id=f"RUN-{capability_id.upper()}-IMMUTABILITY",
                agent_id="cmo",
                capability_id=capability_id,
                parameters={"platform": "adversarial", "payload": "must require approval"},
            )
        )
        self.assertEqual(
            ExecutionStatus.APPROVAL_REQUIRED,
            receipt.status,
            "Mutating a caller-visible descriptor must never downgrade live ToolGateway policy authority.",
        )

    def test_retained_registration_reference_cannot_downgrade_policy(self) -> None:
        registry = CapabilityRegistry()
        descriptor = self._critical_publish_descriptor("immutable_publish_input")
        registry.register_capability(descriptor)

        self._downgrade(descriptor)

        self._assert_policy_still_authoritative(registry, "immutable_publish_input")

    def test_get_return_value_cannot_downgrade_policy(self) -> None:
        registry = CapabilityRegistry()
        registry.register_capability(self._critical_publish_descriptor("immutable_publish_get"))

        exposed = registry.get_capability("immutable_publish_get")
        self.assertIsNotNone(exposed)
        assert exposed is not None
        self._downgrade(exposed)

        self._assert_policy_still_authoritative(registry, "immutable_publish_get")

    def test_list_return_value_cannot_downgrade_policy(self) -> None:
        registry = CapabilityRegistry()
        registry.register_capability(self._critical_publish_descriptor("immutable_publish_list"))

        exposed = next(
            item
            for item in registry.list_capabilities()
            if item.capability_id == "immutable_publish_list"
        )
        self._downgrade(exposed)

        self._assert_policy_still_authoritative(registry, "immutable_publish_list")

    def test_agent_list_return_value_cannot_downgrade_policy(self) -> None:
        registry = CapabilityRegistry()
        registry.register_capability(self._critical_publish_descriptor("immutable_publish_agent_list"))

        exposed = next(
            item
            for item in registry.list_capabilities_for_agent("cmo")
            if item.capability_id == "immutable_publish_agent_list"
        )
        self._downgrade(exposed)

        self._assert_policy_still_authoritative(registry, "immutable_publish_agent_list")


if __name__ == "__main__":
    unittest.main()
