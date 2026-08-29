from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway
from integrations.models.registry import (
    ModelMetadata,
    ModelPolicy,
    ModelRegistry,
    ModelTarget,
    ProviderRegistry,
)


class CountingAdapter(BaseModelAdapter):
    provider_name = "agg"
    default_model = "unknown-model"
    cost_policy = CostPolicy.FREE_TIER_ALLOWED

    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        return ModelResponse(
            request_id=request.request_id,
            provider="agg",
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content="executed",
        )


def _gateway(model_id: str, *, metadata: ModelMetadata | None = None):
    adapter = CountingAdapter()
    providers = ProviderRegistry()
    providers.register_custom_adapter(adapter)
    models = ModelRegistry()
    if metadata is not None:
        models.register_model(metadata)
    gateway = UniversalModelGateway(
        provider_registry=providers,
        model_registry=models,
        model_policy=ModelPolicy(
            global_target=ModelTarget(provider_id="agg", model_id=model_id),
            fallback_chain=[],
            free_only_mode=True,
        ),
        free_only_mode=True,
    )
    return gateway, adapter


def _request():
    return ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="x")])


def test_verified_paid_model_overrides_generic_provider_free_tier():
    gateway, adapter = _gateway(
        "known-paid-model",
        metadata=ModelMetadata(
            provider_id="agg",
            model_id="known-paid-model",
            display_name="Known Paid",
            cost_tier=CostPolicy.PAID,
        ),
    )
    response = gateway.generate(_request())
    assert response.status == ModelResponseStatus.ERROR
    assert "FREE_ONLY_POLICY_VIOLATION" in (response.error or "")
    assert adapter.calls == 0


def test_unknown_model_on_free_tier_aggregator_fails_closed():
    gateway, adapter = _gateway("unknown-model")
    response = gateway.generate(_request())
    assert response.status == ModelResponseStatus.ERROR
    assert "FREE_ONLY_POLICY_VIOLATION" in (response.error or "")
    assert adapter.calls == 0


def test_verified_free_model_is_allowed_to_execute():
    gateway, adapter = _gateway(
        "known-free-model",
        metadata=ModelMetadata(
            provider_id="agg",
            model_id="known-free-model",
            display_name="Known Free",
            cost_tier=CostPolicy.FREE_TIER_ALLOWED,
        ),
    )
    response = gateway.generate(_request())
    assert response.status == ModelResponseStatus.SUCCESS
    assert response.content == "executed"
    assert adapter.calls == 1
