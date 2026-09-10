import unittest

from integrations.models.registry import ModelPolicy


class ModelPolicyDefaultFallbackAuthorityV1Tests(unittest.TestCase):
    def test_default_policy_has_no_hidden_alternate_provider_fallbacks(self):
        policy = ModelPolicy()
        self.assertEqual(policy.global_target.provider_id, "xkiro")
        self.assertEqual(
            policy.global_target.model_id,
            "mistralai/mistral-large-2512",
        )
        self.assertEqual(
            policy.fallback_chain,
            [],
            "default ModelPolicy must leave fallback authority to explicit Settings instead of injecting alternate providers",
        )


if __name__ == "__main__":
    unittest.main()
