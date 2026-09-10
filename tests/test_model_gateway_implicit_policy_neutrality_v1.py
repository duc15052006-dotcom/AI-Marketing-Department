import unittest

from integrations.models.base import CostPolicy
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ProviderDefinition, ProviderRegistry


class ModelGatewayImplicitPolicyNeutralityV1Tests(unittest.TestCase):
    def _gateway(self):
        registry = ProviderRegistry()
        registry.register_provider(
            ProviderDefinition(
                provider_id="acme-lab",
                adapter_type="OPENAI_COMPATIBLE",
                display_name="Acme Lab",
                base_url="https://models.example.invalid/v1",
                credential_ref="ENV:ACME_LAB_API_KEY",
                default_model="acme-reasoner-v7",
                cost_policy=CostPolicy.FREE_TIER_ALLOWED,
            )
        )
        return UniversalModelGateway(
            provider_registry=registry,
            default_provider="acme-lab",
            free_only_mode=False,
        )

    def test_explicit_default_provider_uses_its_registry_model(self):
        gateway = self._gateway()
        policy = gateway.model_policy
        self.assertEqual(policy.global_target.provider_id, "acme-lab")
        self.assertEqual(
            policy.global_target.model_id,
            "acme-reasoner-v7",
            "implicit policy must derive the selected provider's configured default model instead of injecting another provider's model",
        )

    def test_implicit_policy_has_no_foreign_fallback_injection(self):
        gateway = self._gateway()
        policy = gateway.model_policy
        self.assertEqual(
            policy.fallback_chain,
            [],
            "implicit policy must not silently inject xkiro/gemini or any unrelated fallback provider",
        )
        self.assertEqual(
            gateway.resolve_candidate_chain(),
            [("acme-lab", "acme-reasoner-v7")],
            "candidate routing must stay pinned to the configured default provider until Settings supplies an explicit fallback chain",
        )


if __name__ == "__main__":
    unittest.main()
