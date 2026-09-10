import unittest

from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelRole,
    StreamDelta,
)
from integrations.models.config_service import ProviderErrorCode
from integrations.models.gateway import ProviderHealth, UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


class _RecordingConfigService:
    def __init__(self):
        self.errors = []

    def record_error(self, provider_id, error_code):
        self.errors.append((provider_id, error_code))


class _SilentTruncatedAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "silent-truncated"

    def generate(self, request):
        raise AssertionError("sync generate must not be used")

    def generate_stream(self, request):
        yield StreamDelta(content="", finish_reason=None)
        return


class _PartialTruncatedAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "partial-truncated"

    def generate(self, request):
        raise AssertionError("sync generate must not be used")

    def generate_stream(self, request):
        yield StreamDelta(content="partial", finish_reason=None)
        return


class ModelGatewayStreamTruncatedHealthV1Tests(unittest.TestCase):
    def _run(self, adapter):
        registry = ProviderRegistry()
        registry.register_custom_adapter(adapter)
        config_service = _RecordingConfigService()
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id=adapter.provider_name, model_id="model-a"),
            fallback_chain=[],
            free_only_mode=False,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=config_service,
            model_policy=policy,
            free_only_mode=False,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=10.0,
        )
        return gateway, config_service, list(gateway.generate_stream(request))

    def _assert_accounted_unavailable(self, gateway, config_service, provider_name):
        self.assertEqual(
            config_service.errors,
            [(provider_name, ProviderErrorCode.OTHER)],
            "unexpected provider stream EOF must feed provider error accounting",
        )
        self.assertEqual(
            gateway.get_provider_health(provider_name),
            ProviderHealth.UNAVAILABLE,
            "a provider that violates the terminal stream protocol must not remain AVAILABLE",
        )

    def test_silent_precontent_eof_records_protocol_failure_health(self):
        adapter = _SilentTruncatedAdapter()
        gateway, config_service, deltas = self._run(adapter)

        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].finish_reason, "error")
        self.assertIsNotNone(deltas[0].error)
        self.assertEqual(deltas[0].error.code, "STREAM_TRUNCATED")
        self._assert_accounted_unavailable(
            gateway, config_service, adapter.provider_name
        )

    def test_postcontent_eof_records_protocol_failure_without_fallback(self):
        adapter = _PartialTruncatedAdapter()
        gateway, config_service, deltas = self._run(adapter)

        self.assertEqual(len(deltas), 2)
        self.assertEqual(deltas[0].content, "partial")
        self.assertIsNone(deltas[0].finish_reason)
        self.assertEqual(deltas[1].finish_reason, "error")
        self.assertIsNotNone(deltas[1].error)
        self.assertEqual(deltas[1].error.code, "STREAM_TRUNCATED")
        self._assert_accounted_unavailable(
            gateway, config_service, adapter.provider_name
        )


if __name__ == "__main__":
    unittest.main()
