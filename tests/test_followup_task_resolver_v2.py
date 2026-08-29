from types import SimpleNamespace

from chat.task_resolver import FollowupKind, ResearchDepth, resolve_followup


def msg(role, content, message_id):
    return SimpleNamespace(role=role, content=content, message_id=message_id)


def test_table_followup_reuses_previous_answer_without_research_route():
    history = [
        msg("user", "nghiên cứu mức độ tăng trưởng của ngành hàng decor", "u1"),
        msg("assistant", "Các chỉ số tăng trưởng đã tìm được...", "a1"),
    ]
    resolved = resolve_followup("đưa các chỉ số mức độ tăng trưởng này thành bảng cho tôi", history)
    assert resolved.kind == FollowupKind.TRANSFORM_EXISTING
    assert resolved.route_hint == "GENERAL_CONVERSATION"
    assert resolved.referenced_message_ids == ("a1",)


def test_deepen_followup_inherits_prior_research_subject_never_literal_search():
    history = [
        msg("user", "nghiên cứu mức độ tăng trưởng của ngành hàng decor", "u1"),
        msg("assistant", "Kết quả ban đầu", "a1"),
        msg("user", "đưa các chỉ số mức độ tăng trưởng này thành bảng cho tôi", "u2"),
        msg("assistant", "| Chỉ số | Giá trị |", "a2"),
    ]
    resolved = resolve_followup("tìm kỹ cho tôi", history)
    assert resolved.kind == FollowupKind.DEEPEN_RESEARCH
    assert resolved.route_hint == "RESEARCH_INQUIRY"
    assert resolved.research_depth == ResearchDepth.DEEP
    assert "ngành hàng decor" in resolved.resolved_objective
    assert resolved.resolved_objective.strip() != "tìm kỹ cho tôi"
    assert resolved.referenced_message_ids == ("u1",)


def test_deepen_without_prior_research_fails_open_to_normal_router_not_invent_topic():
    history = [msg("assistant", "Xin chào", "a1")]
    resolved = resolve_followup("tìm kỹ cho tôi", history)
    assert resolved.kind == FollowupKind.NONE
    assert resolved.route_hint is None
    assert resolved.resolved_objective == "tìm kỹ cho tôi"


def test_current_just_appended_user_message_is_excluded_defensively():
    raw = "tìm kỹ cho tôi"
    history = [
        msg("user", "research competitor pricing for decor", "u1"),
        msg("assistant", "Initial result", "a1"),
        msg("user", raw, "u2"),
    ]
    resolved = resolve_followup(raw, history)
    assert resolved.kind == FollowupKind.DEEPEN_RESEARCH
    assert "competitor pricing for decor" in resolved.resolved_objective
