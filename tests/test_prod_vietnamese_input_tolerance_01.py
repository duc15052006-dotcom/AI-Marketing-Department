"""Tests for PROD-VIETNAMESE-INPUT-TOLERANCE-01.

Validates:
1. Normalization & Accent Folding (Unicode NFC, lowercasing, folding, whitespace collapse).
2. Raw User Text Preservation (never mutated or overwritten).
3. Bounded Typo & Abbreviation Tolerance (GREETING & IDENTITY shortcuts).
4. Route Precedence (Marketing Deliverable > Research Inquiry > Conversational Greeting).
5. Research Without Accents.
6. Full Marketing Without Accents.
7. Proper Noun / Entity Preservation (BNA, BN Group, HEL0, XJN Corporation).
8. No Model-Based Spell Correction (deterministic routing layer).
9. Chat Engine Offline Fallback & User-Facing Error Sanitization.
10. Provider Configuration Test Contamination Regression Guard.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from chat.engine import ChatConversationEngine
from chat.router import (
    ConversationIntent,
    ConversationRouter,
    RoutingDecision,
    fold_vietnamese,
    normalize_for_routing,
)
from chat.session import ChatRole, ChatSession
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import ModelTarget, UniversalModelGateway
from integrations.models.secret_store import SecureSecretStore
from integrations.models.settings_manager import ModelSettingsManager


class TestVietnameseInputTolerance01(unittest.TestCase):
    """Suite verifying accent folding, typo tolerance, route precedence, and isolation."""

    def setUp(self) -> None:
        self.router = ConversationRouter(model_gateway=None)

    # ------------------------------------------------------------------
    # 1. Normalization & Diacritic Folding
    # ------------------------------------------------------------------

    def test_01_fold_vietnamese_basic(self) -> None:
        raw = "Phân tích thị trường & Đèn LED"
        folded = fold_vietnamese(raw)
        self.assertEqual(folded, "Phan tich thi truong & Den LED")
        self.assertEqual(raw, "Phân tích thị trường & Đèn LED", "Raw text must not be mutated")

    def test_02_normalize_for_routing_collapses_whitespace_and_folds(self) -> None:
        raw = "   Xin   Chào   Bạn  ! ! !   "
        normalized = normalize_for_routing(raw)
        self.assertEqual(normalized, "xin chao ban")
        self.assertEqual(raw, "   Xin   Chào   Bạn  ! ! !   ", "Raw input must remain verbatim")

    def test_03_normalize_bounded_typos_and_abbreviations(self) -> None:
        self.assertEqual(normalize_for_routing("xjn chao"), "xin chao")
        self.assertEqual(normalize_for_routing("chao bn"), "chao ban")
        self.assertEqual(normalize_for_routing("chaoban"), "chao ban")
        self.assertEqual(normalize_for_routing("helo"), "hello")
        self.assertEqual(normalize_for_routing("bn la ai"), "ban la ai")
        self.assertEqual(normalize_for_routing("ban la aii"), "ban la ai")

    # ------------------------------------------------------------------
    # 2. Greeting & Identity Tolerant Routing
    # ------------------------------------------------------------------

    def test_04_greetings_matrix(self) -> None:
        greetings = [
            "xin chào",
            "xin chao",
            "xjn chao",
            "chao ban",
            "chào bạn",
            "chao bn",
            "chào bn",
            "chaoban",
            "hello",
            "helo",
            "hi",
            "ban la ai",
            "bạn là ai",
            "bn la ai",
            "ban là aii",
            "what is your name",
            "who are you",
            "cảm ơn",
            "cam on",
            "thanks",
            "thank you",
            "tạm biệt",
            "tam biet",
            "goodbye",
            "bye",
        ]
        for msg in greetings:
            decision = self.router.route(msg)
            self.assertEqual(
                decision.intent,
                ConversationIntent.GENERAL_CONVERSATION,
                f"Failed on greeting message: {msg}",
            )
            self.assertEqual(
                decision.reason_code,
                "DETERMINISTIC_GREETING",
                f"Incorrect reason code for greeting: {msg}",
            )
            self.assertGreaterEqual(decision.confidence, 0.95)

    # ------------------------------------------------------------------
    # 3. Research Inquiries Without Accents
    # ------------------------------------------------------------------

    def test_05_research_inquiries_matrix(self) -> None:
        research_queries = [
            "tim xu huong den decor moi nhat",
            "tìm xu hướng đèn decor mới nhất",
            "nghien cuu gia ban gaming hien nay",
            "Tìm thông tin mới nhất về đèn decor",
            "Tim thong tin moi nhat ve den decor",
            "khao sat du lieu thi truong den trang tri",
            "tim nguon du lieu ban gaming",
            "search for latest market data on decor",
        ]
        for q in research_queries:
            decision = self.router.route(q)
            self.assertEqual(
                decision.intent,
                ConversationIntent.RESEARCH_INQUIRY,
                f"Failed on research query: {q}",
            )
            self.assertEqual(
                decision.reason_code,
                "DETERMINISTIC_RESEARCH_KEYWORD",
                f"Incorrect reason code for research query: {q}",
            )

    # ------------------------------------------------------------------
    # 4. Full Marketing Workflows Without Accents
    # ------------------------------------------------------------------

    def test_06_marketing_workflows_matrix(self) -> None:
        marketing_queries = [
            "nghien cuu thi truong decor va lap chien luoc 30 ngay",
            "phan tich thi truong roi lap content plan, ngan sach va KPI",
            "xin chao hay lap ke hoach marketing 30 ngay",
            "xay dung chien luoc marketing cho san pham moi",
            "lap campaign tiktok voi ngan sach 50 trieu",
            "content hello kitty marketing plan 30 ngay",
        ]
        for mq in marketing_queries:
            decision = self.router.route(mq)
            self.assertEqual(
                decision.intent,
                ConversationIntent.MARKETING_WORKFLOW,
                f"Failed on marketing workflow: {mq}",
            )
            self.assertEqual(
                decision.reason_code,
                "DETERMINISTIC_MARKETING_KEYWORD",
                f"Incorrect reason code for marketing query: {mq}",
            )

    # ------------------------------------------------------------------
    # 5. Route Precedence (Marketing > Research > Greeting)
    # ------------------------------------------------------------------

    def test_07_greeting_plus_research_routes_to_research(self) -> None:
        decision = self.router.route("chao ban, tim xu huong den decor moi nhat")
        self.assertEqual(decision.intent, ConversationIntent.RESEARCH_INQUIRY)
        self.assertEqual(decision.reason_code, "DETERMINISTIC_RESEARCH_KEYWORD")

    def test_08_greeting_plus_marketing_routes_to_marketing(self) -> None:
        decision = self.router.route(
            "xin chao, nghien cuu thi truong decor va lap chien luoc marketing 30 ngay, 5 content va KPI"
        )
        self.assertEqual(decision.intent, ConversationIntent.MARKETING_WORKFLOW)
        self.assertEqual(decision.reason_code, "DETERMINISTIC_MARKETING_KEYWORD")

    # ------------------------------------------------------------------
    # 6. Entity & Proper Noun Preservation (Negative Tests)
    # ------------------------------------------------------------------

    def test_09_entity_preservation_bna(self) -> None:
        raw = "Phân tích thương hiệu BNA Việt Nam"
        decision = self.router.route(raw)
        self.assertEqual(decision.intent, ConversationIntent.MARKETING_WORKFLOW)
        # Verify raw text is never corrupted
        self.assertEqual(raw, "Phân tích thương hiệu BNA Việt Nam")

    def test_10_entity_preservation_standalone_and_groups(self) -> None:
        entities = [
            ("BN Group", ConversationIntent.GENERAL_CONVERSATION),
            ("BNA", ConversationIntent.GENERAL_CONVERSATION),
            ("HEL0 Studio", ConversationIntent.GENERAL_CONVERSATION),
            ("XJN Corporation", ConversationIntent.GENERAL_CONVERSATION),
        ]
        for name, expected in entities:
            decision = self.router.route(name)
            self.assertEqual(decision.intent, expected, f"Failed on entity: {name}")
            # Neither BNA nor BN Group must become greeting
            self.assertNotEqual(decision.reason_code, "DETERMINISTIC_GREETING", f"Entity {name} misclassified as greeting")

    # ------------------------------------------------------------------
    # 7. No Model-Based Spell Correction (Deterministic Gateway Contract)
    # ------------------------------------------------------------------

    def test_11_no_model_calls_for_deterministic_routing(self) -> None:
        mock_gateway = MagicMock(spec=UniversalModelGateway)
        router_with_gw = ConversationRouter(model_gateway=mock_gateway)

        # Deterministic greeting
        router_with_gw.route("chao ban")
        mock_gateway.generate.assert_not_called()

        # Deterministic research
        router_with_gw.route("tim xu huong den decor")
        mock_gateway.generate.assert_not_called()

        # Deterministic marketing
        router_with_gw.route("lap ke hoach marketing 30 ngay")
        mock_gateway.generate.assert_not_called()

    # ------------------------------------------------------------------
    # 8. Chat Engine Offline Fallback & Error Sanitization
    # ------------------------------------------------------------------

    def test_12_chat_engine_offline_fallback_tolerant(self) -> None:
        engine = ChatConversationEngine(model_gateway=None)
        session = ChatSession(chat_id="test-session-01", optional_project_id="p1")

        # Mock gateway failure
        mock_failing_gw = MagicMock(spec=UniversalModelGateway)
        mock_failing_gw.generate.return_value = ModelResponse(
            request_id="req-1",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.ERROR,
            error="PROVIDER_UNAVAILABLE: gemini HTTP 599 Server Error. Detail: <urlopen error [WinError 10061] Connection refused>",
        )
        engine.model_gateway = mock_failing_gw

        # Greeting offline fallback succeeds
        res_greeting = engine.generate_chat_response(session, "chao ban")
        self.assertTrue(res_greeting["success"])
        self.assertIn("Xin chào!", res_greeting["content"])

        # Identity offline fallback succeeds
        res_identity = engine.generate_chat_response(session, "bn la ai")
        self.assertTrue(res_identity["success"])
        self.assertIn("AI Marketing Department", res_identity["content"])

    def test_13_chat_engine_error_sanitization_no_winerror_leak(self) -> None:
        engine = ChatConversationEngine(model_gateway=None)
        session = ChatSession(chat_id="test-session-02", optional_project_id="p1")

        mock_failing_gw = MagicMock(spec=UniversalModelGateway)
        mock_failing_gw.generate.return_value = ModelResponse(
            request_id="req-2",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.ERROR,
            error="PROVIDER_UNAVAILABLE: gemini HTTP 599 Server Error. Detail: <urlopen error [WinError 10061] No connection could be made because the target machine actively refused it>",
        )
        engine.model_gateway = mock_failing_gw

        # Non-greeting query where model is required
        res = engine.generate_chat_response(session, "Phân tích số liệu phức tạp này cho tôi")
        self.assertFalse(res["success"])
        # User-facing message must be sanitized
        self.assertNotIn("WinError 10061", res["content"])
        self.assertNotIn("HTTP 599", res["content"])
        self.assertIn("Không thể hoàn tất phản hồi từ mô hình AI", res["content"])
        # Public machine error stays canonical; raw transport detail is not exposed.
        self.assertEqual(res["error"], "PROVIDER_RESPONSE_ERROR")
        self.assertNotIn("WinError 10061", str(res.get("public_error", {})))

    # ------------------------------------------------------------------
    # 9. Provider Configuration Test Contamination Regression Guard
    # ------------------------------------------------------------------

    def test_14_production_settings_isolation_and_no_mock_artifacts(self) -> None:
        mgr = ModelSettingsManager()
        settings = mgr.get_settings()
        # Verify no test artifacts persisted in real settings
        self.assertNotIn("prodwire_prov", settings.providers)
        self.assertNotIn("norev_enable", settings.providers)
        self.assertNotIn("stale_matrix", settings.providers)
        self.assertNotEqual(settings.global_target.provider_id, "prodwire_prov")
        # Verify genuine providers exist
        self.assertIn("gemini", settings.providers)
        self.assertIn("xkiro", settings.providers)


    def test_15_arbitrary_query_does_not_receive_fake_offline_success(self) -> None:
        engine = ChatConversationEngine(model_gateway=None)
        session = ChatSession(chat_id="test-session-03", optional_project_id="p1")

        mock_failing_gw = MagicMock(spec=UniversalModelGateway)
        mock_failing_gw.generate.return_value = ModelResponse(
            request_id="req-3",
            provider="xkiro",
            model_name="deepseek/deepseek-v4-flash",
            status=ModelResponseStatus.ERROR,
            error="PROVIDER_UNAVAILABLE: xkiro HTTP 599 Server Error. Detail: <urlopen error [WinError 10061] Connection refused>",
        )
        engine.model_gateway = mock_failing_gw

        # Arbitrary explanation query
        res = engine.generate_chat_response(session, "giai thich cho toi CPA la gi")
        self.assertFalse(res["success"])
        self.assertNotIn("WinError 10061", res["content"])
        self.assertIn("Không thể hoàn tất phản hồi từ mô hình AI", res["content"])
        self.assertEqual(res["error"], "PROVIDER_RESPONSE_ERROR")
        self.assertNotIn("WinError 10061", str(res.get("public_error", {})))


if __name__ == "__main__":
    unittest.main()
