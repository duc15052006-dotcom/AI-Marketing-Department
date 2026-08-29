"""Deterministic conversation continuity and follow-up resolution.

This module resolves high-confidence conversational references before routing.
It never uses an LLM to rewrite entities or invent missing context. Ambiguous
requests remain unchanged and can be handled by the normal router/assistant.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence

from chat.router import fold_vietnamese, normalize_for_routing
from chat.session import ChatMessage, ChatRole


class FollowupIntent(str, Enum):
    NONE = "NONE"
    TRANSFORM_EXISTING = "TRANSFORM_EXISTING"
    DEEPEN_RESEARCH = "DEEPEN_RESEARCH"


@dataclass(frozen=True)
class ResolvedConversationTurn:
    original_text: str
    effective_text: str
    followup_intent: FollowupIntent = FollowupIntent.NONE
    active_objective: Optional[str] = None
    research_depth: str = "STANDARD"
    reason_code: str = "NO_FOLLOWUP_RESOLUTION"


_RESEARCH_MARKERS = (
    "nghien cuu",
    "research",
    "thi truong",
    "market research",
    "doi thu",
    "competitor",
    "xu huong",
    "trend",
    "muc do tang truong",
    "growth",
)

_DEEPEN_EXACT = {
    "tim ky cho toi",
    "tim ky hon cho toi",
    "nghien cuu ky cho toi",
    "nghien cuu ky hon",
    "nghien cuu sau hon",
    "tim sau hon",
    "dao sau hon",
    "deep research",
    "research deeper",
    "dig deeper",
    "look deeper",
}

_TRANSFORM_MARKERS = (
    "thanh bang",
    "dua cac chi so",
    "dua so lieu",
    "lap bang",
    "tao bang",
    "tom tat lai",
    "viet lai",
    "chuyen thanh",
    "format lai",
    "make a table",
    "put this into a table",
    "summarize this",
    "rewrite this",
)

_REFERENCE_MARKERS = (
    "nay",
    "do",
    "tren",
    "vua roi",
    "cac chi so",
    "so lieu",
    "ket qua",
    "these",
    "this",
    "those",
    "above",
    "previous",
)


def _norm(text: str) -> str:
    return normalize_for_routing(text or "")


def _is_deepen(text: str) -> bool:
    norm = _norm(text)
    if norm in _DEEPEN_EXACT:
        return True
    return any(marker in norm for marker in ("tim ky hon", "nghien cuu sau hon", "dao sau", "research deeper", "deep research"))


def _is_transform(text: str) -> bool:
    norm = _norm(text)
    has_transform = any(marker in norm for marker in _TRANSFORM_MARKERS)
    has_reference = any(marker in norm.split() or marker in norm for marker in _REFERENCE_MARKERS)
    return has_transform and has_reference


def _looks_like_research_objective(text: str) -> bool:
    norm = _norm(text)
    if not norm or _is_deepen(text) or _is_transform(text):
        return False
    return any(marker in norm for marker in _RESEARCH_MARKERS)


def find_prior_research_objective(messages: Sequence[ChatMessage], current_text: str = "") -> Optional[str]:
    """Find the nearest explicit prior research request, never a vague follow-up."""
    current = (current_text or "").strip()
    for msg in reversed(messages):
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        text = (msg.content or "").strip()
        if role != ChatRole.USER.value or not text or text == current:
            continue
        if _looks_like_research_objective(text):
            return text
    return None


def resolve_conversation_turn(messages: Sequence[ChatMessage], current_text: str) -> ResolvedConversationTurn:
    """Resolve only high-confidence transform/deepen follow-ups.

    Deepen requests are rewritten to the explicit prior research objective so
    the research subsystem never receives a literal query like "tìm kỹ cho tôi".
    Transform requests remain textually intact but are tagged to stay in the
    conversational path where prior assistant content is available.
    """
    text = (current_text or "").strip()
    prior_research = find_prior_research_objective(messages, current_text=text)

    if _is_deepen(text) and prior_research:
        effective = (
            f"{prior_research}\n\n"
            "Yêu cầu tiếp nối đã được giải quyết từ lịch sử hội thoại: nghiên cứu sâu hơn chủ đề trên. "
            "Mở rộng nhiều góc truy vấn, ưu tiên nguồn gốc/nguồn đáng tin cậy, kiểm tra ngày và đối chiếu các claim quan trọng."
        )
        return ResolvedConversationTurn(
            original_text=text,
            effective_text=effective,
            followup_intent=FollowupIntent.DEEPEN_RESEARCH,
            active_objective=prior_research,
            research_depth="DEEP",
            reason_code="PRIOR_RESEARCH_OBJECTIVE_RESOLVED",
        )

    if _is_transform(text):
        # A transform only has meaning if there is a prior assistant answer.
        has_prior_assistant = any(
            (m.role.value if hasattr(m.role, "value") else str(m.role)) == ChatRole.ASSISTANT.value
            and bool((m.content or "").strip())
            and (m.content or "").strip() != text
            for m in messages
        )
        if has_prior_assistant:
            return ResolvedConversationTurn(
                original_text=text,
                effective_text=text,
                followup_intent=FollowupIntent.TRANSFORM_EXISTING,
                active_objective=prior_research,
                research_depth="STANDARD",
                reason_code="PRIOR_ASSISTANT_OUTPUT_RESOLVED",
            )

    return ResolvedConversationTurn(original_text=text, effective_text=text)
