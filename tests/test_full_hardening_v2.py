from chat.conversation_state import FollowupIntent, resolve_conversation_turn
from chat.session import ChatMessage, ChatRole
from runtime.agent_skills import PERMANENT_AGENT_IDS, get_agent_skill_contract
from runtime.public_errors import PublicRuntimeError, public_error_payload
from app_api.streaming import sanitize_error_for_stream
from connectors.analytics_connector import RealAnalyticsConnector
from tools.adapters import AnalyticsAdapter, MediaCreationAdapter
from tools.receipts import ExecutionMode


def _msg(role: ChatRole, content: str) -> ChatMessage:
    return ChatMessage(chat_id="CHAT-T", role=role, content=content)


def test_exactly_five_skill_agents_and_final_cmo_reuses_cmo():
    assert PERMANENT_AGENT_IDS == ("cmo", "intelligence", "strategist", "creative", "performance")
    assert len(PERMANENT_AGENT_IDS) == 5
    assert get_agent_skill_contract("final_cmo") == get_agent_skill_contract("cmo")


def test_decor_followup_transform_reuses_prior_answer_without_new_research():
    history = [
        _msg(ChatRole.USER, "nghiên cứu mức độ tăng trưởng của ngành hàng decor"),
        _msg(ChatRole.ASSISTANT, "Tăng trưởng được tổng hợp từ các nguồn đã nghiên cứu."),
    ]
    resolved = resolve_conversation_turn(history, "đưa các chỉ số mức độ tăng trưởng này thành bảng cho tôi")
    assert resolved.followup_intent == FollowupIntent.TRANSFORM_EXISTING
    assert resolved.effective_text == "đưa các chỉ số mức độ tăng trưởng này thành bảng cho tôi"


def test_decor_deepen_never_literal_searches_vague_followup():
    history = [
        _msg(ChatRole.USER, "nghiên cứu mức độ tăng trưởng của ngành hàng decor"),
        _msg(ChatRole.ASSISTANT, "Kết quả nghiên cứu decor"),
        _msg(ChatRole.USER, "đưa các chỉ số mức độ tăng trưởng này thành bảng cho tôi"),
        _msg(ChatRole.ASSISTANT, "| Chỉ số | Giá trị |\n|---|---|\n| Ví dụ | dữ liệu |"),
    ]
    resolved = resolve_conversation_turn(history, "tìm kỹ cho tôi")
    assert resolved.followup_intent == FollowupIntent.DEEPEN_RESEARCH
    assert resolved.research_depth == "DEEP"
    assert resolved.active_objective == "nghiên cứu mức độ tăng trưởng của ngành hàng decor"
    assert "ngành hàng decor" in resolved.effective_text
    assert resolved.effective_text.strip() != "tìm kỹ cho tôi"


def test_arbitrary_exception_is_never_reflected_in_public_error_payload():
    secret = "Bearer abc123 SUPER_SECRET=/private/key"
    payload = public_error_payload(RuntimeError(secret))
    rendered = str(payload)
    assert "abc123" not in rendered
    assert "SUPER_SECRET" not in rendered
    assert "/private/key" not in rendered
    assert payload["code"] == "RUNTIME_INTERNAL_ERROR"


def test_sse_arbitrary_error_fails_closed():
    payload = sanitize_error_for_stream(ValueError("api_key=SUPER_SECRET_VALUE"))
    assert payload["code"] == "RUNTIME_INTERNAL_ERROR"
    assert "SUPER_SECRET_VALUE" not in str(payload)
    assert payload["message"] == payload["safe_message"]


def test_media_mock_does_not_claim_rendered_success():
    res = MediaCreationAdapter().execute("image_generation", {"prompt": "hero"})
    assert res.success is False
    assert res.execution_mode == ExecutionMode.MOCK
    assert not res.artifact_refs
    assert (res.data or {}).get("status") == "NOT_EXECUTED"


def test_generic_analytics_mock_does_not_fabricate_statistics():
    res = AnalyticsAdapter().execute("experiment_result_analysis", {})
    assert res.success is False
    data = res.data or {}
    assert "p_value" not in data
    assert "confidence_interval" not in data
    assert "sample_size" not in data


def test_real_analytics_kpi_requires_inputs_and_is_real_when_computed():
    conn = RealAnalyticsConnector()
    missing = conn.execute("kpi_calculation", {"metric_name": "roas"})
    assert missing.success is False
    assert missing.error_code == "MISSING_INPUTS"

    calc = conn.execute("kpi_calculation", {
        "metric_name": "roas", "spend": 100.0, "revenue": 250.0, "clicks": 20, "conversions": 5,
    })
    assert calc.success is True
    assert calc.execution_mode == ExecutionMode.REAL
    assert calc.data["roas"] == 2.5
    assert calc.data["cac"] == 20.0


def test_real_analytics_never_fabricates_attribution_or_pvalue_without_data():
    conn = RealAnalyticsConnector()
    res = conn.execute("attribution_data_access", {})
    assert res.success is False
    assert res.error_code == "MISSING_OBSERVED_DATA"
    assert "p_value" not in (res.data or {})
    assert "channel_weights" not in (res.data or {})


def test_public_runtime_error_preserves_typed_safe_fields():
    err = PublicRuntimeError(
        code="RATE_LIMITED", category="RATE_LIMIT", safe_message="Try later.", retryable=True,
        http_status=429, provider="xkiro", model_name="m", stage="INTELLIGENCE", agent="INTELLIGENCE",
    )
    payload = sanitize_error_for_stream(err)
    assert payload["code"] == "RATE_LIMITED"
    assert payload["retryable"] is True
    assert payload["http_status"] == 429
    assert payload["stage"] == "INTELLIGENCE"
