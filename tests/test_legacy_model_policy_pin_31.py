"""Regressions for run-pinned ModelPolicy legacy compatibility and fail-closed reconstruction."""

import unittest

from integrations.models.base import ModelResponse, ModelResponseStatus
from runtime.engine import FiveAgentDepartmentRuntime


class CapturingGateway:
    def __init__(self) -> None:
        self.model_policy = None
        self.provider_registry = None
        self.calls = []

    def generate(self, request, **kwargs):
        self.calls.append((request, kwargs))
        return ModelResponse(
            request_id=request.request_id,
            provider="policy_test",
            model_name="policy_test",
            status=ModelResponseStatus.SUCCESS,
            content="ok",
        )


class LegacyModelPolicyPin31Tests(unittest.TestCase):
    def _runtime(self):
        gateway = CapturingGateway()
        return FiveAgentDepartmentRuntime(model_gateway=gateway), gateway

    def test_default_run_pin_uses_canonical_timeout_seconds(self):
        runtime, _ = self._runtime()
        context = runtime.start_run(objective="Test canonical default model pin")

        self.assertEqual(context.model_policy["free_only_mode"], True)
        self.assertEqual(context.model_policy["timeout_seconds"], 60.0)
        self.assertNotIn("timeout", context.model_policy)

    def test_legacy_flat_timeout_alias_is_reconstructed_and_unknown_noise_is_ignored(self):
        runtime, gateway = self._runtime()
        context = runtime.start_run(objective="Test flat legacy model pin")
        context.model_policy = {
            "free_only_mode": True,
            "timeout": 37.0,
            "legacy_noise": "ignored",
        }

        content, error = runtime._call_agent_llm(
            "cmo",
            "Frame the marketing objective without inventing evidence.",
            "Objective: test legacy pin",
            context=context,
        )

        self.assertEqual(error, None)
        self.assertEqual(content, "ok")
        pinned = gateway.calls[-1][1]["model_policy"]
        self.assertIsNotNone(pinned)
        self.assertEqual(pinned.timeout_seconds, 37.0)
        self.assertTrue(pinned.free_only_mode)

    def test_legacy_nested_timeout_alias_is_supported(self):
        runtime, gateway = self._runtime()
        context = runtime.start_run(objective="Test nested legacy model pin")
        context.model_policy = {
            "policy": {
                "free_only_mode": True,
                "timeout": 21.0,
                "legacy_noise": "ignored",
            },
            "providers": {},
        }

        content, error = runtime._call_agent_llm(
            "performance",
            "Evaluate only observed performance evidence.",
            "Objective: test nested legacy pin",
            context=context,
        )

        self.assertEqual(error, None)
        self.assertEqual(content, "ok")
        pinned = gateway.calls[-1][1]["model_policy"]
        self.assertEqual(pinned.timeout_seconds, 21.0)

    def test_malformed_governance_boolean_still_fails_closed(self):
        runtime, gateway = self._runtime()
        context = runtime.start_run(objective="Test malformed governance pin")
        context.model_policy = {"free_only_mode": "true", "timeout": 30.0}

        with self.assertRaisesRegex(RuntimeError, "RUN_PINNED_MODEL_CONFIGURATION_INVALID"):
            runtime._call_agent_llm(
                "cmo",
                "Frame the objective.",
                "Objective: malformed governance",
                context=context,
            )
        self.assertEqual(gateway.calls, [])

    def test_unknown_only_policy_fails_closed_instead_of_silently_disappearing(self):
        runtime, gateway = self._runtime()
        context = runtime.start_run(objective="Test unknown-only model pin")
        context.model_policy = {"legacy_noise": "x"}

        with self.assertRaisesRegex(RuntimeError, "RUN_PINNED_MODEL_CONFIGURATION_INVALID"):
            runtime._call_agent_llm(
                "cmo",
                "Frame the objective.",
                "Objective: unknown-only policy",
                context=context,
            )
        self.assertEqual(gateway.calls, [])


if __name__ == "__main__":
    unittest.main()
