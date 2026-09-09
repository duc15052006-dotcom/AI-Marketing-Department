import unittest

from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import ModelPolicy, ModelTarget, ProviderRegistry


SECRET = "super-secret-token-12345"


class _NoopConfigService:
    def record_error(self, provider_id, error_code):
        return None


class _LeakyExceptionAdapter(BaseModelAdapter):
    @property
    def provider_name(self):
        return "leaky"

    def generate(self, request):
        raise RuntimeError(f"upstream rejected Authorization: Bearer {SECRET}")


class ModelGatewayAdapterExceptionSecretRedactionV1Tests(unittest.TestCase):
    def test_adapter_exception_secret_is_not_exposed_in_public_error(self):
        registry = ProviderRegistry()
        registry.register_custom_adapter(_LeakyExceptionAdapter())
        policy = ModelPolicy(
            global_target=ModelTarget(provider_id="leaky", model_id="model-a"),
            fallback_chain=[],
            free_only_mode=True,
        )
        gateway = UniversalModelGateway(
            provider_registry=registry,
            config_service=_NoopConfigService(),
            model_policy=policy,
            free_only_mode=True,
        )
        request = ModelRequest(
            model_name="default",
            messages=[ModelMessage(role=ModelRole.USER, content="hello")],
            timeout_seconds=30.0,
        )

        response = gateway.generate(request, strict_model_pin=True)

        self.assertIsNotNone(response.error)
        self.assertIn("ADAPTER_INVOCATION_EXCEPTION", response.error)
        self.assertNotIn(
            SECRET,
            response.error,
            "Adapter exception secrets must never be copied into public ModelResponse.error.",
        )
        self.assertIn("[REDACTED_TOKEN]", response.error)


if __name__ == "__main__":
    unittest.main()
