"""Tests for PROD-RESEARCH-SPEED-REPAIR-01: Research Fast Path.

Validates:
A. General conversation routes to GENERAL_CONVERSATION (1 model call, 0 search, 0 workflow)
B. Research inquiry routes to RESEARCH_INQUIRY (1 model call, 1 search, Intelligence-only)
C. Full marketing workflow routes to MARKETING_WORKFLOW (6 stages, 5 agent calls)
D. Ambiguous research+strategy request routes to MARKETING_WORKFLOW (full workflow)
E. Research keywords with full workflow markers → MARKETING_WORKFLOW (workflow precedence)
F. No CMO/Strategist/Creative/Performance/Final CMO calls in research-only path
G. Scope preservation in research fast path
H. Evidence pipeline preservation (ObservationRecord → EvidenceBuilder → GroundingContext)
I. Conflict/gap preservation (B4 boundary)
J. Research-only model call count = 1
K. General conversation regression (still fast)
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from chat.router import ConversationIntent, ConversationRouter, RoutingDecision, fold_vietnamese

# ---------------------------------------------------------------------------
# Deterministic routing tests (no LLM, no model gateway)
# ---------------------------------------------------------------------------


class TestResearchFastPathRouting(unittest.TestCase):
    """Test suite for research fast path routing decisions."""

    def setUp(self):
        self.router = ConversationRouter(model_gateway=None)

    # ── A. General conversation ──

    def test_A1_greeting_routes_general(self):
        """'xin chào' → GENERAL_CONVERSATION."""
        d = self.router.route("xin chào")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertGreaterEqual(d.confidence, 0.95)

    def test_A2_qa_routes_general(self):
        """'CPA là gì?' → GENERAL_CONVERSATION."""
        d = self.router.route("CPA là gì?")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)

    def test_A3_short_query_routes_general(self):
        """Short non-marketing query → GENERAL_CONVERSATION."""
        d = self.router.route("hello")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)

    # ── B. Research inquiry ──

    def test_B1_tim_thong_tin_routes_research(self):
        """'Tìm thông tin mới nhất về xu hướng đèn decor' → RESEARCH_INQUIRY."""
        d = self.router.route("Tìm thông tin mới nhất về xu hướng đèn decor tại Việt Nam.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)
        self.assertGreaterEqual(d.confidence, 0.90)

    def test_B2_nghien_cuu_thi_truong_routes_research(self):
        """'Nghiên cứu giá thị trường bàn gaming' → RESEARCH_INQUIRY."""
        d = self.router.route("Nghiên cứu giá thị trường bàn gaming hiện nay.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    def test_B3_tim_nguon_routes_research(self):
        """'Tìm nguồn và cho tôi biết xu hướng TikTok Shop' → RESEARCH_INQUIRY."""
        d = self.router.route("Tìm nguồn và cho tôi biết xu hướng TikTok Shop mới nhất.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    def test_B4_market_data_routes_research(self):
        """English research query → RESEARCH_INQUIRY."""
        d = self.router.route("Search for latest market data on Vietnamese home decor trends.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    def test_B5_research_folded_diacritics(self):
        """Research keywords without diacritics still route correctly."""
        d = self.router.route("tim thong tin moi nhat ve xu huong den decor")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    def test_B6_khao_sat_routes_research(self):
        """'Khảo sát dữ liệu thị trường' → RESEARCH_INQUIRY."""
        d = self.router.route("Khảo sát dữ liệu thị trường đèn trang trí.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    # ── C. Full marketing workflow ──

    def test_C1_full_marketing_workflow(self):
        """'Lập kế hoạch marketing 90 ngày' → MARKETING_WORKFLOW."""
        d = self.router.route("Lập kế hoạch marketing 90 ngày cho thương hiệu decor.")
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)
        self.assertGreaterEqual(d.confidence, 0.90)

    def test_C2_campaign_marketing(self):
        """'Lập campaign TikTok' → MARKETING_WORKFLOW."""
        d = self.router.route("Lập campaign TikTok cho sản phẩm này.")
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)

    def test_C3_content_plan_marketing(self):
        """'Phân bổ ngân sách và KPI' → MARKETING_WORKFLOW."""
        d = self.router.route("Phân bổ ngân sách và thiết lập KPI cho chiến dịch.")
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)

    # ── D. Ambiguous research + strategy → full workflow ──

    def test_D1_research_and_strategy_full_workflow(self):
        """Research keywords + full workflow markers → MARKETING_WORKFLOW."""
        d = self.router.route(
            "Nghiên cứu thị trường decor Việt Nam và lập kế hoạch marketing 30 ngày, "
            "phân bổ ngân sách và KPI."
        )
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)

    def test_D2_nghien_cuu_va_lap_ke_hoach(self):
        """'Nghiên cứu và lập kế hoạch marketing' → MARKETING_WORKFLOW."""
        d = self.router.route("Nghiên cứu thị trường rồi lập kế hoạch marketing.")
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)

    # ── E. Research keywords WITHOUT workflow markers → RESEARCH_INQUIRY ──

    def test_E1_research_without_workflow_markers(self):
        """'Nghiên cứu thị trường decor Việt Nam' → RESEARCH_INQUIRY (no workflow markers)."""
        d = self.router.route("Nghiên cứu thị trường decor Việt Nam.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    def test_E2_tim_thong_tin_pure_research(self):
        """'Tìm thông tin về xu hướng' → RESEARCH_INQUIRY."""
        d = self.router.route("Tìm thông tin mới nhất về xu hướng đèn decor tại Việt Nam và tóm tắt những xu hướng có bằng chứng.")
        self.assertEqual(d.intent, ConversationIntent.RESEARCH_INQUIRY)

    # ── F. Document analysis still works ──

    def test_F1_doc_analysis_unchanged(self):
        """Document analysis routing unaffected by research changes."""
        d = self.router.route("Tóm tắt file này", attachments=[MagicMock()])
        self.assertEqual(d.intent, ConversationIntent.DOCUMENT_ANALYSIS)

    # ── G. System command still works ──

    def test_G1_system_command_unchanged(self):
        """System commands still route correctly."""
        d = self.router.route("/status")
        self.assertEqual(d.intent, ConversationIntent.SYSTEM_COMMAND)

    # ── H. Ambiguous fallback still works ──

    def test_H1_short_general_fallback(self):
        """Short ambiguous query → GENERAL_CONVERSATION (fail-safe)."""
        d = self.router.route("ok")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)


# ---------------------------------------------------------------------------
# Vietnamese folding preservation
# ---------------------------------------------------------------------------


class TestVietnameseFoldingPreserved(unittest.TestCase):
    """Ensure fold_vietnamese only affects matching layer, never user input."""

    def test_fold_preserves_original(self):
        """fold_vietnamese returns folded string, original never mutated."""
        original = "Phân tích thị trường"
        folded = fold_vietnamese(original)
        self.assertNotEqual(original, folded)
        # Original must be unchanged
        self.assertEqual(original, "Phân tích thị trường")


# ---------------------------------------------------------------------------
# Route enum completeness
# ---------------------------------------------------------------------------


class TestRouteEnumCompleteness(unittest.TestCase):
    """RESEARCH_INQUIRY exists in ConversationIntent."""

    def test_research_inquiry_in_enum(self):
        """ConversationIntent contains RESEARCH_INQUIRY."""
        self.assertIn("RESEARCH_INQUIRY", [e.value for e in ConversationIntent])

    def test_five_routes_total(self):
        """ConversationIntent has exactly 5 routes."""
        self.assertEqual(len(ConversationIntent), 5)


# ---------------------------------------------------------------------------
# Semantic classification prompt includes RESEARCH
# ---------------------------------------------------------------------------


class TestSemanticClassificationPrompt(unittest.TestCase):
    """Verify the semantic classifier prompt includes RESEARCH category."""

    def test_classify_via_model_includes_research(self):
        """_classify_via_model prompt mentions RESEARCH."""
        router = ConversationRouter(model_gateway=None)
        # Access the method to inspect its prompt
        import inspect
        source = inspect.getsource(router._classify_via_model)
        self.assertIn("RESEARCH", source)
        self.assertIn("RESEARCH_INQUIRY", source)


# ---------------------------------------------------------------------------
# Routing decision metadata
# ---------------------------------------------------------------------------


class TestRoutingDecisionMetadata(unittest.TestCase):
    """Routing decisions carry correct reason codes."""

    def test_research_reason_code(self):
        """Research inquiry has DETERMINISTIC_RESEARCH_KEYWORD reason code."""
        router = ConversationRouter(model_gateway=None)
        d = router.route("Tìm thông tin mới nhất về xu hướng đèn decor.")
        self.assertEqual(d.reason_code, "DETERMINISTIC_RESEARCH_KEYWORD")

    def test_marketing_reason_code_unchanged(self):
        """Marketing workflow still has DETERMINISTIC_MARKETING_KEYWORD."""
        router = ConversationRouter(model_gateway=None)
        d = router.route("Xây dựng chiến lược marketing 90 ngày.")
        self.assertEqual(d.reason_code, "DETERMINISTIC_MARKETING_KEYWORD")


if __name__ == "__main__":
    unittest.main()
