from integrations.models.base import BaseModelAdapter, CostPolicy, ModelResponse, ModelResponseStatus
from integrations.models.gateway import UniversalModelGateway, resolve_effective_model_cost_policy
from integrations.models.registry import ModelMetadata, ModelPolicy, ModelTarget, ProviderDefinition, ProviderRegistry


class CountingAdapter(BaseModelAdapter):
    provider_name = "agg"
    default_model = "unknown-paid-model"
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
            content="should not run under free-only unknown cost",
        )


def test_verified_model_metadata_overrides_generic_provider_tier():
    meta = ModelMetadata(
        provider_id="agg",
        model_id="paid-model",
        display_name="paid",
        cost_tier=CostPolicy.PAID,
    )
    provider = ProviderDefinition(
        provider_id="agg",
        adapter_type="CUSTOM_INJECTED",
        default_model="paid-model",
        cost_policy=CostPolicy.FREE_TIER_ALLOWED,
    )
    assert resolve_effective_model_cost_policy(meta, provider, None) == CostPolicy.PAID


def test_unknown_model_on_free_tier_aggregator_fails_closed_to_unknown():
    provider = ProviderDefinition(
        provider_id="agg",
        adapter_type="CUSTOM_INJECTED",
        default_model="unknown-model",
        cost_policy=CostPolicy.FREE_TIER_ALLOWED,
    )
    assert resolve_effective_model_cost_policy(None, provider, None) == CostPolicy.UNKNOWN


def test_free_only_gateway_does_not_execute_unknown_cost_model():
    adapter = CountingAdapter()
    registry = ProviderRegistry()
    registry.register_adapter("agg", adapter)
    gateway = UniversalModelGateway(
        provider_registry=registry,
        model_policy=ModelPolicy(
            global_target=ModelTarget(provider_id="agg", model_id="unknown-paid-model"),
            fallback_chain=[],
            free_only_mode=True,
        ),
        free_only_mode=True,
    )
    from integrations.models.base import ModelMessage, ModelRequest, ModelRole
    response = gateway.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="x")]))
    assert response.status == ModelResponseStatus.ERROR
    assert "FREE_ONLY_POLICY_VIOLATION" in (response.error or "")
    assert adapter.calls == 0
