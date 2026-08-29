"""Deterministic conversation follow-up and reference resolution.

This module resolves only high-confidence conversational references before the
normal intent router runs.  It never calls an LLM and never changes authority,
provider, tool, or evidence semantics.

The purpose is deliberately narrow:
- transform-existing follow-ups reuse the previous assistant answer;
- deepen-research follow-ups inherit the previous research objective;
- vague follow-ups are never sent to web search literally when their subject is
  already available in the same chat.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any, List, Optional, Sequence, Tuple

from chat.router import normalize_for_routing


class FollowupKind(str, Enum):
    NONE = "NONE"
    TRANSFORM_EXISTING = "TRANSFORM_EXISTING"
    DEEPEN_RESEARCH = "DEEPEN_RESEARCH"


class ResearchDepth(str, Enum):
    QUICK = "QUICK"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


@dataclass(frozen=True)
class ResolvedFollowup:
    kind: FollowupKind
    raw_user_text: str
    resolved_objective: str
    route_hint: Optional[str]
    research_depth: ResearchDepth = ResearchDepth.STANDARD
    referenced_message_ids: Tuple[str, ...] = ()
    reason_code: str = "NO_HIGH_CONFIDENCE_FOLLOWUP"

    @property
    def is_followup(self) -> bool:
        return self.kind != FollowupKind.NONE


_TRANSFORM_MARKERS = (
    "thanh bang",
    "dua cac chi so",
    "dua nhung chi so",
    "chuyen thanh bang",
    "lap thanh bang",
    "tom tat cai nay",
    "tom tat phan nay",
    "viet lai cai nay",
    "viet lai phan nay",
    "liet ke lai",
    "sap xep lai",
    "so sanh cac chi so nay",
    "turn this into a table",
    "turn these into a table",
    "make this a table",
    "summarize this",
    "summarize the above",
    "rewrite this",
)

_REFERENCE_MARKERS = (
    "nay",
    "do",
    "tren",
    "vua roi",
    "o tren",
    "cac chi so",
    "nhung chi so",
    "ket qua",
    "phan tich",
    "this",
    "these",
    "that",
    "above",
    "previous",
    "those",
)

_DEEPEN_MARKERS = (
    "tim ky",
    "tim ki hon",
    "tim ky hon",
    "nghien cuu ky",
    "nghien cuu sau",
    "dao sau",
    "tim them",
    "kiem tra ky",
    "phan tich sau hon",
    "nghien cuu them",
    "research deeper",
    "research this deeper",
    "dig deeper",
    "look deeper",
    "find more",
    "investigate further",
)

_RESEARCH_SUBJECT_MARKERS = (
    "nghien cuu",
    "tim thong tin",
    "tim hieu",
    "tim nguon",
    "du lieu",
    "thi truong",
    "xu huong",
    "muc do tang truong",
    "doi thu",
    "market research",
    "research",
    "find information",
    "look up",
    "trend",
    "growth",
    "competitor",
)


def _role_value(message: Any) -> str:
    role = getattr(message, "role", "")
    return str(getattr(role, "value", role)).lower()


def _content(message: Any) -> str:
    value = getattr(message, "content", "")
    return value if isinstance(value, str) else ""


def _message_id(message: Any) -> str:
    value = getattr(message, "message_id", "")
    return value if isinstance(value, str) else ""


def _previous_messages(chat_history: Optional[Sequence[Any]], raw_user_text: str) -> List[Any]:
    """Return bounded same-chat history, defensively excluding a just-appended current turn."""
    if not chat_history:
        return []
    items = list(chat_history)[-16:]
    if items and _role_value(items[-1]) == "user" and _content(items[-1]).strip() == raw_user_text.strip():
        items = items[:-1]
    return items


def _latest_by_role(messages: Sequence[Any], role: str) -> Optional[Any]:
    for item in reversed(messages):
        if _role_value(item) == role and _content(item).strip():
            return item
    return None


def _latest_research_user_message(messages: Sequence[Any]) -> Optional[Any]:
    for item in reversed(messages):
        if _role_value(item) != "user":
            continue
        text = _content(item).strip()
        normalized = normalize_for_routing(text)
        if text and any(marker in normalized for marker in _RESEARCH_SUBJECT_MARKERS):
            return item
    return None


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    return any(marker in text for marker in markers)


def resolve_followup(
    raw_user_text: str,
    chat_history: Optional[Sequence[Any]],
) -> ResolvedFollowup:
    """Resolve only deterministic high-confidence follow-ups.

    Unknown/ambiguous inputs deliberately return NONE so the existing router
    remains authoritative.  The resolver never invents a missing topic.
    """
    raw = (raw_user_text or "").strip()
    normalized = normalize_for_routing(raw)
    history = _previous_messages(chat_history, raw)

    if not raw or not history:
        return ResolvedFollowup(
            kind=FollowupKind.NONE,
            raw_user_text=raw,
            resolved_objective=raw,
            route_hint=None,
        )

    previous_assistant = _latest_by_role(history, "assistant")

    # Transform an answer that already exists in this chat.  This must not
    # trigger a fresh research/tool run; the general chat engine already has
    # bounded same-chat history and can perform the requested transformation.
    if previous_assistant and _contains_any(normalized, _TRANSFORM_MARKERS) and _contains_any(normalized, _REFERENCE_MARKERS):
        ref_id = _message_id(previous_assistant)
        return ResolvedFollowup(
            kind=FollowupKind.TRANSFORM_EXISTING,
            raw_user_text=raw,
            resolved_objective=raw,
            route_hint="GENERAL_CONVERSATION",
            research_depth=ResearchDepth.STANDARD,
            referenced_message_ids=(ref_id,) if ref_id else (),
            reason_code="FOLLOWUP_TRANSFORM_EXISTING",
        )

    # A short/deictic deepen request inherits the latest explicit research
    # objective.  Never web-search the literal phrase "tìm kỹ cho tôi".
    if _contains_any(normalized, _DEEPEN_MARKERS):
        research_msg = _latest_research_user_message(history)
        if research_msg is not None:
            subject = _content(research_msg).strip()
            ref_id = _message_id(research_msg)
            resolved = (
                f"{subject}\n\n"
                "Yêu cầu tiếp nối: nghiên cứu sâu hơn, ưu tiên nhiều nguồn độc lập, "
                "đọc nguồn gốc khi có thể, kiểm tra độ mới, đối chiếu mâu thuẫn và "
                "nêu rõ phần chưa đủ bằng chứng."
            )
            return ResolvedFollowup(
                kind=FollowupKind.DEEPEN_RESEARCH,
                raw_user_text=raw,
                resolved_objective=resolved,
                route_hint="RESEARCH_INQUIRY",
                research_depth=ResearchDepth.DEEP,
                referenced_message_ids=(ref_id,) if ref_id else (),
                reason_code="FOLLOWUP_DEEPEN_PRIOR_RESEARCH",
            )

    return ResolvedFollowup(
        kind=FollowupKind.NONE,
        raw_user_text=raw,
        resolved_objective=raw,
        route_hint=None,
    )
