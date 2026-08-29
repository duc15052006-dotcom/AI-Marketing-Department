from tools.adapters import (
    AnalyticsAdapter,
    CreativeTextAdapter,
    FileStorageAdapter,
    HttpAdapter,
    MediaCreationAdapter,
    PublishingAdapter,
    SearchAdapter,
)
from tools.capabilities import CapabilityRegistry
from tools.receipts import ExecutionMode, ExecutionStatus
from tools.tool_gateway import ToolGateway, ToolRequest


FAIL_CLOSED_CODES = {
    "PROVIDER_NOT_CONFIGURED",
    "REAL_MEDIA_CONNECTOR_REQUIRED",
    "REAL_ANALYTICS_CONNECTOR_REQUIRED",
}


def test_generic_default_adapters_fail_closed_instead_of_faking_results():
    cases = [
        (SearchAdapter(), "web_search", {"query": "decor"}),
        (HttpAdapter(), "read_page", {"url": "https://example.org"}),
        (CreativeTextAdapter(), "text_generation_support", {"prompt": "draft"}),
        (MediaCreationAdapter("image_gen_adapter"), "image_generation", {"prompt": "hero"}),
        (PublishingAdapter("social_publish_adapter"), "social_publishing", {"platform": "test"}),
        (AnalyticsAdapter("analytics_adapter"), "analytics_retrieval", {}),
        (FileStorageAdapter(), "file_read", {"path": "x"}),
    ]
    for adapter, capability, params in cases:
        result = adapter.execute(capability, params)
        assert result.success is False
        assert result.error_code in FAIL_CLOSED_CODES
        assert result.execution_mode == ExecutionMode.MOCK
        assert not result.artifact_refs
        assert result.data is None


def test_tool_gateway_media_placeholder_never_reports_rendered_success():
    gateway = ToolGateway(capability_registry=CapabilityRegistry())
    receipt = gateway.execute(ToolRequest(
        run_id="RUN-FAKE-GUARD",
        agent_id="creative",
        capability_id="image_generation",
        parameters={"prompt": "hero"},
    ))
    assert receipt.status == ExecutionStatus.ERROR
    assert receipt.error_class in FAIL_CLOSED_CODES
    assert receipt.data is None
    assert receipt.artifact_references == []


def test_tool_gateway_analytics_placeholder_never_invents_statistics():
    gateway = ToolGateway(capability_registry=CapabilityRegistry())
    receipt = gateway.execute(ToolRequest(
        run_id="RUN-FAKE-GUARD-2",
        agent_id="performance",
        capability_id="analytics_retrieval",
        parameters={},
    ))
    assert receipt.status == ExecutionStatus.ERROR
    payload = str(receipt.model_dump())
    for forbidden in ("3.45", "14200", "0.012", "confidence_interval"):
        assert forbidden not in payload
