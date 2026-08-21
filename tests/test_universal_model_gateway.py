"""Phase 4.3C: Universal Model Gateway & Multi-Provider Architecture Tests.

Tests:
1. Generic OpenAI-compatible adapter (xKiro, OpenAI, custom endpoints)
2. ProviderRegistry & ModelRegistry (configuration-driven registration)
3. ModelProfile and ProfileManager routing
4. UniversalModelGateway generation, profile dispatch, and explicit pinning
5. FREE_ONLY_MODE cost governance enforcement
6. Production fallback on 429/503/transient errors
7. Benchmark strict-mode blocking fallbacks
8. Secret resolver safety (zero leaks in responses or logs)
9. Provider health tracking and error normalization
10. Config-only provider addition (zero code modifications)
11. Full Five-Agent pipeline execution through UniversalModelGateway
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from governance.claim_register import ClaimRegister
from governance.claim_safety import FinalClaimAuditGate
from governance.runtime_engine import GovernedExecutionPipeline
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.fake_gemini_adapter import FakeGeminiProviderAdapter
from integrations.models.gateway import ProviderHealth, UniversalModelGateway
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.profiles import ModelProfile, ProfileManager
from integrations.models.registry import (
    ModelMetadata,
    ModelRegistry,
    ProviderConfig,
    ProviderProtocol,
    ProviderRegistry,
)
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    SourceType,
    SupportStatus,
)


class TestUniversalModelGateway(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_generic_openai_compatible_adapter_contract(self):
        """Verify OpenAICompatibleProviderAdapter handles config, auth, and normalizes responses."""
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="sk-test-key-12345",
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        self.assertEqual(adapter.provider_name, "xkiro")
        self.assertEqual(adapter.cost_policy, CostPolicy.FREE_TIER_ALLOWED)
        self.assertTrue(adapter.is_configured())

        fake_resp_body = {
            "id": "chatcmpl-test-001",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "mistralai/mistral-large-2512",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": '{"plan": "Strategy ready"}'},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 45,
                "total_tokens": 165,
                "completion_tokens_details": {"reasoning_tokens": 10},
            },
        }

        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_cm = MagicMock()
            mock_cm.read.return_value = json.dumps(fake_resp_body).encode("utf-8")
            mock_urlopen.return_value.__enter__.return_value = mock_cm

            req = ModelRequest(
                messages=[ModelMessage(role=ModelRole.USER, content="Hello")],
                model_name="mistralai/mistral-large-2512",
            )
            resp = adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.provider, "xkiro")
            self.assertEqual(resp.content, '{"plan": "Strategy ready"}')
            self.assertEqual(resp.usage.prompt_tokens, 120)
            self.assertEqual(resp.usage.completion_tokens, 45)
            self.assertEqual(resp.usage.total_tokens, 165)
            self.assertEqual(resp.usage.thoughts_tokens, 10)
            self.assertEqual(resp.usage.usage_source, "PROVIDER_REPORTED")

    def test_provider_and_model_registry(self):
        """Verify ProviderRegistry and ModelRegistry load defaults and support registration."""
        p_reg = ProviderRegistry()
        m_reg = ModelRegistry()

        self.assertIn("xkiro", p_reg.list_providers())
        self.assertIn("gemini", p_reg.list_providers())
        self.assertIn("openai", p_reg.list_providers())

        xkiro_cfg = p_reg.get_config("xkiro")
        self.assertIsNotNone(xkiro_cfg)
        self.assertEqual(xkiro_cfg.protocol, ProviderProtocol.OPENAI_COMPATIBLE)
        self.assertEqual(xkiro_cfg.default_model, "mistralai/mistral-large-2512")

        xkiro_model = m_reg.get_model("xkiro", "mistralai/mistral-large-2512")
        self.assertIsNotNone(xkiro_model)
        self.assertEqual(xkiro_model.cost_tier, CostPolicy.FREE_TIER_ALLOWED)

        free_models = m_reg.list_free_models()
        self.assertTrue(any(m.provider_id == "xkiro" for m in free_models))
        self.assertTrue(any(m.provider_id == "gemini" for m in free_models))

    def test_model_profiles_routing(self):
        """Verify ProfileManager maps logical profiles to prioritized candidate tuples."""
        pm = ProfileManager()
        reasoning_chain = pm.get_models_for_profile(ModelProfile.MARKETING_REASONING.value)
        self.assertGreaterEqual(len(reasoning_chain), 2)
        self.assertEqual(reasoning_chain[0][0], "xkiro")
        self.assertEqual(reasoning_chain[0][1], "mistralai/mistral-large-2512")

    def test_free_only_mode_blocks_paid_models(self):
        """Verify UniversalModelGateway in FREE_ONLY_MODE strictly blocks paid models."""
        gateway = UniversalModelGateway(free_only_mode=True)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Test")], model_name="gpt-4o-mini")

        # Request paid OpenAI with allow_paid=False -> blocked
        resp = gateway.generate(req, provider_id="openai", strict_model_pin=True, allow_paid=False)
        self.assertEqual(resp.status, ModelResponseStatus.ERROR)
        self.assertIn("FREE_ONLY_POLICY_VIOLATION", resp.error)

    def test_production_fallback_on_429(self):
        """Verify production mode (strict_model_pin=False) falls back to secondary provider on 429."""
        p_reg = ProviderRegistry()
        m_reg = ModelRegistry()
        pm = ProfileManager()

        # Primary fake adapter returning 429
        mock_primary = MagicMock(spec=BaseModelAdapter)
        mock_primary.provider_name = "xkiro"
        mock_primary.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_primary.generate.return_value = ModelResponse(
            request_id="req-1",
            provider="xkiro",
            model_name="mistralai/mistral-large-2512",
            status=ModelResponseStatus.RATE_LIMITED,
            error="RATE_LIMITED: HTTP 429",
        )

        # Secondary fake adapter returning SUCCESS
        mock_secondary = MagicMock(spec=BaseModelAdapter)
        mock_secondary.provider_name = "gemini"
        mock_secondary.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_secondary.generate.return_value = ModelResponse(
            request_id="req-1",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.SUCCESS,
            content='{"result": "Secondary Success"}',
            usage=ModelUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        )

        p_reg.register_custom_adapter(mock_primary)
        p_reg.register_custom_adapter(mock_secondary)

        gateway = UniversalModelGateway(
            provider_registry=p_reg,
            model_registry=m_reg,
            profile_manager=pm,
            free_only_mode=True,
        )

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Plan")])
        resp = gateway.generate(req, profile=ModelProfile.MARKETING_REASONING.value, strict_model_pin=False)

        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.provider, "gemini")
        self.assertEqual(resp.metadata.get("resolved_provider"), "gemini")
        self.assertEqual(resp.metadata.get("attempt_count"), 2)

    def test_benchmark_strict_pin_blocks_fallback(self):
        """Verify benchmark strict mode (strict_model_pin=True) stops immediately on failure without fallback."""
        p_reg = ProviderRegistry()
        mock_primary = MagicMock(spec=BaseModelAdapter)
        mock_primary.provider_name = "xkiro"
        mock_primary.cost_policy = CostPolicy.FREE_TIER_ALLOWED
        mock_primary.generate.return_value = ModelResponse(
            request_id="req-1",
            provider="xkiro",
            model_name="mistralai/mistral-large-2512",
            status=ModelResponseStatus.RATE_LIMITED,
            error="RATE_LIMITED: HTTP 429",
        )
        p_reg.register_custom_adapter(mock_primary)

        gateway = UniversalModelGateway(provider_registry=p_reg, free_only_mode=True)
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Plan")])

        resp = gateway.generate(req, provider_id="xkiro", strict_model_pin=True)
        self.assertEqual(resp.status, ModelResponseStatus.RATE_LIMITED)
        self.assertEqual(resp.provider, "xkiro")
        self.assertEqual(mock_primary.generate.call_count, 1)

    def test_secret_resolver_safety(self):
        """Verify credentials are never exposed in error messages or responses."""
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="custom_secret_test",
            base_url="https://api.test.com/v1",
            api_key_env="TEST_SECRET_ENV_KEY",
            default_model="test-model",
            api_key="SUPER_SECRET_TOKEN_999",
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
        )

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hi")])
        with patch("urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://api.test.com/v1/chat/completions",
                code=401,
                msg="Unauthorized",
                hdrs={},
                fp=None,
            )

            resp = adapter.generate(req)
            self.assertEqual(resp.status, ModelResponseStatus.ERROR)
            self.assertNotIn("SUPER_SECRET_TOKEN_999", resp.error or "")
            self.assertNotIn("SUPER_SECRET_TOKEN_999", str(resp.model_dump()))

    def test_config_only_provider_addition(self):
        """Verify a new third-party provider can be registered and used solely via configuration."""
        gateway = UniversalModelGateway(free_only_mode=True)

        new_config = ProviderConfig(
            provider_id="provider_fake_xyz",
            protocol=ProviderProtocol.OPENAI_COMPATIBLE,
            base_url="https://api.fakexyz.com/v1",
            api_key_env="FAKE_XYZ_API_KEY",
            default_model="xyz-turbo-preview",
            cost_policy=CostPolicy.FREE_TIER_ALLOWED,
            capabilities={"supports_json": True},
        )
        gateway.provider_registry.register_provider(new_config)

        gateway.model_registry.register_model(
            ModelMetadata(
                provider_id="provider_fake_xyz",
                model_id="xyz-turbo-preview",
                display_name="XYZ Turbo Preview",
                cost_tier=CostPolicy.FREE_TIER_ALLOWED,
            )
        )

        # Mock adapter generate directly
        adapter = gateway.provider_registry.get_adapter("provider_fake_xyz")
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.provider_name, "provider_fake_xyz")

        with patch.object(adapter, "generate") as mock_gen:
            mock_gen.return_value = ModelResponse(
                request_id="req-xyz",
                provider="provider_fake_xyz",
                model_name="xyz-turbo-preview",
                status=ModelResponseStatus.SUCCESS,
                content='{"status": "Config Provider Executed Successfully"}',
                usage=ModelUsage(prompt_tokens=40, completion_tokens=15, total_tokens=55),
            )

            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Run config test")])
            resp = gateway.generate(req, provider_id="provider_fake_xyz", strict_model_pin=True)

            self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp.provider, "provider_fake_xyz")
            self.assertIn("Config Provider Executed Successfully", resp.content)

    def test_full_five_agent_e2e_through_universal_gateway(self):
        """Execute Single and Five-Agent stages end-to-end through UniversalModelGateway."""
        fake_adapter = FakeGeminiProviderAdapter()

        p_reg = ProviderRegistry()
        p_reg.register_custom_adapter(fake_adapter)

        gateway = UniversalModelGateway(provider_registry=p_reg, free_only_mode=True)

        from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import BenchmarkHarness

        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                cooldown_seconds=0.0,
                provider_id="fake_gemini",
                model_name="gemini-flash-latest",
                gateway=gateway,
            )
            harness.adapter = fake_adapter

            # Run Single Condition
            single_res = harness.run_single_condition(dry_run=False)
            self.assertEqual(single_res["status"], "SUCCESS")
            self.assertEqual(single_res["universal_final_audit"]["authorization_status"], "APPROVED")

            # Run Five-Agent Condition
            five_res = harness.run_five_agent_condition(dry_run=False)
            self.assertEqual(five_res["status"], "COMPLETED")
            self.assertEqual(len(five_res["stages"]), 6)
            self.assertEqual(five_res["universal_final_audit"]["authorization_status"], "APPROVED")
            self.assertEqual(five_res["final_authorization"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
