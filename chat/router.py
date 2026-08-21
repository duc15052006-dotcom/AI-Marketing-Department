"""Conversation Intent Router for AI Marketing Department.

Classifies incoming chat messages into distinct operational routes:
- GENERAL_CONVERSATION: Greetings, casual chat, general Q&A, coding, explanations, translation.
- DOCUMENT_ANALYSIS: Summarization, Q&A, extraction on attached files/URLs using Session Knowledge.
- MARKETING_WORKFLOW: Complex marketing work triggering the Five-Agent Department runtime.
- SYSTEM_COMMAND: Slash commands or system-level administrative actions.

Deterministic heuristic routing is evaluated first (zero LLM overhead).
Ambiguous cases fallback to lightweight model classification via UniversalModelGateway.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from integrations.models.base import ModelMessage, ModelRequest, ModelRole
from integrations.models.gateway import UniversalModelGateway


class ConversationIntent(str, Enum):
    """Execution route for an incoming chat message."""
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"
    DOCUMENT_ANALYSIS = "DOCUMENT_ANALYSIS"
    MARKETING_WORKFLOW = "MARKETING_WORKFLOW"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"


@dataclass
class RoutingDecision:
    """Deterministic or model-assisted routing decision."""
    intent: ConversationIntent
    confidence: float
    reason_code: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "intent": self.intent.value,
            "confidence": self.confidence,
            "reason_code": self.reason_code,
            "metadata": self.metadata,
        }


class ConversationRouter:
    """Infrastructure router determining execution pathway for chat inputs."""

    def __init__(self, model_gateway: Optional[UniversalModelGateway] = None) -> None:
        self.model_gateway = model_gateway

        # Regex patterns for deterministic matching (Vietnamese + English)
        self._greetings_pattern = re.compile(
            r"^\s*(xin\s+chào|chào\s+bạn|chào|hello|hi|hey|good\s+morning|good\s+afternoon|good\s+evening|"
            r"bạn\s+là\s+ai|who\s+are\s+you|bạn\s+tên\s+gì|what\s+is\s+your\s+name|"
            r"bạn\s+biết\s+tiếng\s+việt\s+không|do\s+you\s+speak\s+vietnamese|do\s+you\s+speak\s+english|"
            r"cảm\s+ơn|thanks|thank\s+you|tạm\s+biệt|goodbye|bye)\s*[!?.]*\s*$",
            re.IGNORECASE,
        )

        self._identity_history_pattern = re.compile(
            r"^\s*(tôi\s+tên\s+(là\s+)?[\w\s]+|tôi\s+tên\s+gì|what\s+is\s+my\s+name|my\s+name\s+is\s+[\w\s]+|"
            r"nhắc\s+lại\s+câu\s+trước|bạn\s+vừa\s+nói\s+gì|what\s+did\s+you\s+just\s+say)\s*[!?.]*\s*$",
            re.IGNORECASE,
        )

        self._qa_general_pattern = re.compile(
            r"^\s*(cpa\s+là\s+gì|roas\s+là\s+gì|ctr\s+là\s+gì|cac\s+là\s+gì|ltv\s+là\s+gì|seo\s+là\s+gì|"
            r"what\s+is\s+cpa|what\s+is\s+roas|what\s+is\s+ctr|what\s+is\s+cac|what\s+is\s+ltv|"
            r"giải\s+thích\s+|explain\s+|định\s+nghĩa\s+|define\s+|viết\s+code\s+|write\s+code\s+|"
            r"viết\s+lại\s+đoạn\s+này|rewrite\s+this|dịch\s+câu\s+này|translate\s+this)\b",
            re.IGNORECASE,
        )

        self._doc_keywords = re.compile(
            r"\b(tóm\s+tắt\s+file|tóm\s+tắt\s+tài\s+liệu|đọc\s+file|đọc\s+tài\s+liệu|nội\s+dung\s+file|"
            r"so\s+sánh\s+(\d+\s+)?file|trích\s+xuất|dựa\s+trên\s+file|trong\s+file|file\s+này\s+nói\s+gì|"
            r"summarize\s+this\s+file|summarize\s+this\s+pdf|summarize\s+document|read\s+this\s+file|"
            r"what\s+does\s+this\s+file\s+say|extract\s+from\s+file|compare\s+files)\b",
            re.IGNORECASE,
        )

        self._marketing_explicit_pattern = re.compile(
            r"\b(lập\s+kế\s+hoạch\s+marketing|lập\s+chiến\s+lược|xây\s*(dựng)?\s*chiến\s+lược|chiến\s+lược\s+marketing|chiến\s+lược\s+gtm|"
            r"tạo\s+chiến\s+lược\s+gtm|lập\s+campaign|chạy\s+campaign|chiến\s+dịch\s+tiktok|chiến\s+dịch\s+meta|"
            r"chiến\s+dịch\s+quảng\s+cáo|phân\s+tích\s+thị\s+trường|nghiên\s+cứu\s+đối\s+thủ|định\s+vị\s+sản\s+phẩm|"
            r"cấu\s+trúc\s+định\s+vị|tạo\s+\d+\s+concepts|kịch\s+bản\s+video\s+ngắn|kịch\s+bản\s+quảng\s+cáo|"
            r"phân\s+bổ\s+ngân\s+sách|mô\s+hình\s+phân\s+bổ|marketing\s+strategy|gtm\s+strategy|gtm\s+plan|"
            r"build\s+marketing\s+plan|launch\s+campaign|create\s+ad\s+concepts|competitor\s+intelligence|"
            r"positioning\s+architecture|creative\s+hooks|budget\s+allocation|five-agent\s+department|5\s+agents)\b",
            re.IGNORECASE,
        )

    def route(
        self,
        message: str,
        attachments: Optional[List[Any]] = None,
        chat_history: Optional[List[Any]] = None,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> RoutingDecision:
        """Evaluate input and return deterministic or model-assisted routing decision."""
        text = (message or "").strip()
        has_attachments = bool(attachments and len(attachments) > 0)

        # 1. System Command Route
        if text.startswith("/"):
            return RoutingDecision(
                intent=ConversationIntent.SYSTEM_COMMAND,
                confidence=1.0,
                reason_code="SYSTEM_SLASH_COMMAND",
            )

        # 2. Explicit Greetings & Basic Identity Multi-turn Checks
        if self._greetings_pattern.match(text):
            return RoutingDecision(
                intent=ConversationIntent.GENERAL_CONVERSATION,
                confidence=0.99,
                reason_code="DETERMINISTIC_GREETING",
            )

        if self._identity_history_pattern.match(text):
            return RoutingDecision(
                intent=ConversationIntent.GENERAL_CONVERSATION,
                confidence=0.98,
                reason_code="DETERMINISTIC_IDENTITY_OR_HISTORY",
            )

        if self._qa_general_pattern.search(text):
            return RoutingDecision(
                intent=ConversationIntent.GENERAL_CONVERSATION,
                confidence=0.95,
                reason_code="DETERMINISTIC_QA_OR_EXPLANATION",
            )

        # 3. Document Analysis Checks (when attachments are present or doc keywords used)
        if has_attachments:
            # If user explicitly requests full marketing workflow on document:
            # e.g., "Đọc tài liệu này và xây chiến lược marketing"
            if self._marketing_explicit_pattern.search(text):
                return RoutingDecision(
                    intent=ConversationIntent.MARKETING_WORKFLOW,
                    confidence=0.92,
                    reason_code="DOC_AUGMENTED_MARKETING_WORKFLOW",
                    metadata={"has_attachments": True},
                )
            # Default for attachment queries or summary requests:
            return RoutingDecision(
                intent=ConversationIntent.DOCUMENT_ANALYSIS,
                confidence=0.95,
                reason_code="ATTACHMENT_DOCUMENT_ANALYSIS",
                metadata={"has_attachments": True},
            )

        if self._doc_keywords.search(text):
            return RoutingDecision(
                intent=ConversationIntent.DOCUMENT_ANALYSIS,
                confidence=0.90,
                reason_code="DOCUMENT_QUERY_KEYWORDS",
            )

        # 4. Explicit Marketing Workflow Triggers
        if self._marketing_explicit_pattern.search(text):
            return RoutingDecision(
                intent=ConversationIntent.MARKETING_WORKFLOW,
                confidence=0.95,
                reason_code="DETERMINISTIC_MARKETING_KEYWORD",
            )

        # 5. Short Queries & General Conversational Fallback
        # Short phrases (< 8 words) without explicit marketing triggers are general chat
        word_count = len(text.split())
        if word_count < 8:
            return RoutingDecision(
                intent=ConversationIntent.GENERAL_CONVERSATION,
                confidence=0.85,
                reason_code="SHORT_GENERAL_QUERY",
            )

        # 6. Fallback or Lightweight LLM Classification for Ambiguous Cases
        if self.model_gateway is not None:
            try:
                llm_intent = self._classify_via_model(text)
                if llm_intent:
                    return RoutingDecision(
                        intent=llm_intent,
                        confidence=0.80,
                        reason_code="MODEL_CLASSIFICATION",
                    )
            except Exception:
                pass

        # Default fallback is GENERAL_CONVERSATION
        return RoutingDecision(
            intent=ConversationIntent.GENERAL_CONVERSATION,
            confidence=0.75,
            reason_code="DEFAULT_GENERAL_FALLBACK",
        )

    def _classify_via_model(self, text: str) -> Optional[ConversationIntent]:
        """Perform lightweight single-token intent classification."""
        if not self.model_gateway:
            return None

        prompt = (
            "Classify the following user message into exactly one category:\n"
            "- GENERAL: normal conversation, greeting, Q&A, definitions, coding, rewriting\n"
            "- DOCS: questions about attached files or documents\n"
            "- MARKETING: comprehensive marketing strategy, multi-channel ad campaigns, positioning architecture, GTM planning, budget allocation\n\n"
            f"User message: \"{text[:300]}\"\n\n"
            "Respond with only the category word (GENERAL, DOCS, or MARKETING):"
        )

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
            temperature=0.0,
            max_tokens=10,
        )

        resp = self.model_gateway.generate(req)
        if resp and resp.content:
            ans = resp.content.strip().upper()
            if "MARKETING" in ans:
                return ConversationIntent.MARKETING_WORKFLOW
            elif "DOC" in ans:
                return ConversationIntent.DOCUMENT_ANALYSIS
            elif "GENERAL" in ans:
                return ConversationIntent.GENERAL_CONVERSATION

        return None
