"""PHASE INPUT-01/INPUT-02 — Noisy-language routing regression evidence.

These tests exercise the REAL production ConversationRouter (chat/router.py).
They encode DESIRED acceptance behavior for noisy Vietnamese input.

History:
  - INPUT-01 created this suite as defect evidence: 10/19 tests failed
    against the pre-repair router (exact diacritic regexes + SHORT_GENERAL_QUERY
    preempting semantic classification).
  - INPUT-02 repaired the routing architecture (accent-folded deterministic
    matching layer; semantic classification reachable for ALL ambiguous input,
    including short messages and attachment turns). The desired-behavior
    assertions below are UNCHANGED; only three stale INPUT-01 sub-assertions
    (cases C, F, G) that documented "model is never consulted" were corrected
    to "at most one classification call per route()" — they encoded the bug
    itself, not desired behavior.
  - This suite is now a permanent regression guard: 19/19 must pass.

Case map (id -> desired intent):
  A  "Phân tích thị trường"                        -> MARKETING_WORKFLOW   (baseline, must keep passing)
  B  "phan tich thi truong"                        -> MARKETING_WORKFLOW   (no diacritics)
  C  "phan tihc thi truogn"                        -> MARKETING_WORKFLOW   (transposition typos)
  D  "lap chien luoc mkt"                          -> MARKETING_WORKFLOW   (abbreviation)
  E  "nghien cuu doi thu"                          -> MARKETING_WORKFLOW   (no-diacritic competitor research)
  F  "tooi muoons phaan tichs thij truwowngf"      -> MARKETING_WORKFLOW   (telex-like noise)
  G  "phan tihc competitor cho sp nay"             -> MARKETING_WORKFLOW   (mixed VI/EN + typo)
  H  "xin chaof"                                   -> GENERAL_CONVERSATION (greeting typo stays general)
  I  "cpa la gi"                                   -> GENERAL_CONVERSATION (general Q&A without accents)
  J  "tom tat file nay"                            -> DOCUMENT_ANALYSIS    (document intent, no accents)
  K  "tom tat tai lieu nay ddi"                    -> DOCUMENT_ANALYSIS    (document intent with typo)
  L  attachment + "doc file nay"                   -> DOCUMENT_ANALYSIS
  M  attachment + "doc file nay roi lap chien luoc mkt" -> MARKETING_WORKFLOW
  N  short-but-valid marketing command must NOT be forced to GENERAL
     merely because it has fewer than 8 words (SHORT_GENERAL_QUERY gate).
  O  unknown/random conversational text must remain GENERAL_CONVERSATION
     and the router must not over-route everything to MARKETING.
  P  slash commands must remain SYSTEM_COMMAND.
  R  raw user text must be preserved; routing must be deterministic.

Root-cause hypothesis per case (verified by the run output, see report):
  ROOT_CAUSE_MAP = {
    "B": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "C": ["EXACT_REGEX_DEPENDENCE", "TYPO_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "D": ["EXACT_REGEX_DEPENDENCE", "ABBREVIATION_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "E": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "F": ["EXACT_REGEX_DEPENDENCE", "TYPO_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "G": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "TYPO_INTOLERANCE",
          "ABBREVIATION_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "J": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "K": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "TYPO_INTOLERANCE",
          "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "M": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "ABBREVIATION_INTOLERANCE",
          "DOC_AUGMENTED_MARKETING_BRANCH_EXACT_REGEX"],
    "N": ["SHORT_GENERAL_QUERY_PRECEDENCE"],
    "MODEL_UNREACHABILITY": ["SHORT_GENERAL_QUERY returns GENERAL before the model fallback "
                             "is consulted, so semantic classification is unreachable for "
                             "any unmatched message under 8 words."],
  }

Constraints honored:
  - Real ConversationRouter only; no fake router implementation.
  - No spell-correction layer, no typo dictionary beyond the tiny stub lexicon
    used ONLY inside the mock gateway to observe model reachability.
  - No new agent; no production file modified in this phase.
"""

import re
import unittest
from typing import Any, List, Optional

from chat.router import ConversationIntent, ConversationRouter
from chat.session import AttachmentType, ChatAttachment
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
)
from integrations.models.gateway import UniversalModelGateway


ROOT_CAUSE_MAP = {
    "B": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "C": ["EXACT_REGEX_DEPENDENCE", "TYPO_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "D": ["EXACT_REGEX_DEPENDENCE", "ABBREVIATION_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "E": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "F": ["EXACT_REGEX_DEPENDENCE", "TYPO_INTOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "G": [
        "EXACT_REGEX_DEPENDENCE",
        "MISSING_ACCENT_TOLERANCE",
        "TYPO_INTOLERANCE",
        "ABBREVIATION_INTOLERANCE",
        "SHORT_GENERAL_QUERY_PRECEDENCE",
    ],
    "J": ["EXACT_REGEX_DEPENDENCE", "MISSING_ACCENT_TOLERANCE", "SHORT_GENERAL_QUERY_PRECEDENCE"],
    "K": [
        "EXACT_REGEX_DEPENDENCE",
        "MISSING_ACCENT_TOLERANCE",
        "TYPO_INTOLERANCE",
        "SHORT_GENERAL_QUERY_PRECEDENCE",
    ],
    "M": [
        "EXACT_REGEX_DEPENDENCE",
        "MISSING_ACCENT_TOLERANCE",
        "ABBREVIATION_INTOLERANCE",
        "DOC_AUGMENTED_MARKETING_BRANCH_EXACT_REGEX",
    ],
    "N": ["SHORT_GENERAL_QUERY_PRECEDENCE"],
}


class SemanticRoutingStubGateway(UniversalModelGateway):
    """Mock gateway representing an idealized free-tier semantic classifier.

    Purpose: observe whether ConversationRouter actually REACHES model-based
    classification. It records every classification call and answers from a
    tiny noisy-tolerant stem lexicon. This stub exists ONLY inside this test;
    it does not bypass production routing (the real router decides whether or
    not to consult it).
    """

    _MARKETING_STEMS = (
        "tich",           # phan tich / phân tích / phaan tichs / tichs
        "chien luoc",     # chiến lược variants
        "mkt",
        "competitor",
        "doi thu",        # đối thủ variants
        "thi truong",     # thị trường variants
        "campaign",
        "gtm",
        "marketing",
    )
    _DOC_STEMS = ("tom tat", "tai lieu", "file", "summar", "document")

    @staticmethod
    def _token_signature(token: str) -> frozenset:
        """Letter-multiset signature so a real semantic model's permutation
        tolerance can be simulated for single-token stems (e.g. 'tihc' ~
        'tich', 'truogn' ~ 'truong'). Mock-only; production router never does
        this."""
        from collections import Counter

        return frozenset(Counter(token).items())

    def _matches_stems(self, lowered: str, stems) -> bool:
        tokens = re.findall(r"\w+", lowered)
        signatures = {self._token_signature(t) for t in tokens}
        for stem in stems:
            if stem in lowered:
                return True
            if " " not in stem and self._token_signature(stem) in signatures:
                return True
        return False

    def __init__(self) -> None:
        super().__init__(free_only_mode=True)
        self.classify_calls: List[str] = []

    @property
    def classify_call_count(self) -> int:
        return len(self.classify_calls)

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        last_msg = request.messages[-1].content if request.messages else ""
        # Only respond when invoked as the router's single-token classifier.
        if "Respond with only the category word" not in last_msg:
            return ModelResponse(
                request_id=request.request_id,
                provider="semantic_stub",
                model_name="stub-model",
                status=ModelResponseStatus.SUCCESS,
                content="GENERAL",
            )

        # Extract ONLY the embedded user message; the prompt boilerplate
        # itself contains words like "MARKETING" and must not be classified.
        marker = 'User message: "'
        start = last_msg.find(marker)
        if start != -1:
            payload = last_msg[start + len(marker):]
            end = payload.rfind('"')
            if end != -1:
                payload = payload[:end]
        else:
            payload = last_msg

        self.classify_calls.append(payload)
        lowered = payload.lower()

        if self._matches_stems(lowered, self._MARKETING_STEMS):
            answer = "MARKETING"
        elif self._matches_stems(lowered, self._DOC_STEMS):
            answer = "DOC"
        else:
            answer = "GENERAL"

        return ModelResponse(
            request_id=request.request_id,
            provider="semantic_stub",
            model_name="stub-model",
            status=ModelResponseStatus.SUCCESS,
            content=answer,
        )


class FailingClassifierGateway(SemanticRoutingStubGateway):
    """Classifier whose generate() raises — simulates provider crash."""

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        last_msg = request.messages[-1].content if request.messages else ""
        if "Respond with only the category word" in last_msg:
            self.classify_calls.append("<RAISED>")
            raise RuntimeError("CLASSIFIER_PROVIDER_CRASH")
        return super().generate(request, **kwargs)


class GarbageClassifierGateway(SemanticRoutingStubGateway):
    """Classifier that answers with unparseable output (no category token)."""

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        last_msg = request.messages[-1].content if request.messages else ""
        if "Respond with only the category word" in last_msg:
            marker = 'User message: "'
            start = last_msg.find(marker)
            payload = last_msg[start + len(marker):] if start != -1 else last_msg
            end = payload.rfind('"')
            self.classify_calls.append(payload[:end] if end != -1 else payload)
            return ModelResponse(
                request_id=request.request_id,
                provider="garbage_stub",
                model_name="stub-model",
                status=ModelResponseStatus.SUCCESS,
                content="PURPLE MONKEY DISHWASHER 42?!",
            )
        return super().generate(request, **kwargs)


class TestNoisyLanguageRouting(unittest.TestCase):
    """Desired-behavior regression suite for noisy-language routing."""

    def setUp(self) -> None:
        self.semantic_gateway = SemanticRoutingStubGateway()
        self.router_semantic = ConversationRouter(model_gateway=self.semantic_gateway)
        self.router_plain = ConversationRouter(model_gateway=None)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_attachment(self, chat_id: str = "CHAT-NOISY-1") -> ChatAttachment:
        return ChatAttachment(
            chat_id=chat_id,
            filename_or_url="product_brief.pdf",
            attachment_type=AttachmentType.PDF,
            content="Doanh thu Q2 tang 20%. San pham chinh: tai nghe khong day.",
        )

    def _assert_desired_intent(
        self,
        case_id: str,
        router: ConversationRouter,
        raw_text: str,
        expected_intent: ConversationIntent,
        attachments: Optional[List[Any]] = None,
        require_model_consulted: Optional[bool] = None,
    ) -> None:
        snapshot = raw_text
        decision = router.route(raw_text, attachments=attachments)

        self.assertEqual(
            raw_text,
            snapshot,
            f"[CASE {case_id}] raw user text must be preserved unmodified",
        )
        self.assertEqual(
            decision.intent,
            expected_intent,
            f"[CASE {case_id}] desired intent not met; reason_code="
            f"{decision.reason_code}; root causes={ROOT_CAUSE_MAP.get(case_id, 'see report')}",
        )

        if require_model_consulted is True:
            self.assertGreaterEqual(
                self.semantic_gateway.classify_call_count,
                1,
                f"[CASE {case_id}] expected model semantic classification to be consulted",
            )
        if require_model_consulted is False:
            self.assertEqual(
                self.semantic_gateway.classify_call_count,
                0,
                f"[CASE {case_id}] model was consulted but this case documents that it "
                f"must not need to be (deterministic layer should handle it)",
            )

    # ------------------------------------------------------------------
    # CASE A — correct Vietnamese baseline (must keep passing)
    # ------------------------------------------------------------------

    def test_case_a_baseline_vietnamese_marketing(self) -> None:
        decision = self.router_plain.route("Phân tích thị trường")
        self.assertEqual(
            decision.intent,
            ConversationIntent.MARKETING_WORKFLOW,
            f"[CASE A] baseline broke; reason_code={decision.reason_code}",
        )
        self.assertEqual(decision.reason_code, "DETERMINISTIC_MARKETING_KEYWORD")

    # ------------------------------------------------------------------
    # CASE B — Vietnamese without diacritics
    # ------------------------------------------------------------------

    def test_case_b_no_diacritics_marketing(self) -> None:
        self._assert_desired_intent(
            "B",
            self.router_semantic,
            "phan tich thi truong",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        self.assertEqual(
            self.semantic_gateway.classify_call_count,
            0,
            "[CASE B] SHORT_GENERAL_QUERY fired before model fallback could be consulted "
            "(model semantic fallback unreachable for short ambiguous messages)",
        )

    # ------------------------------------------------------------------
    # CASE C — character transposition / typo
    # ------------------------------------------------------------------

    def test_case_c_transposition_typo_marketing(self) -> None:
        self._assert_desired_intent(
            "C",
            self.router_semantic,
            "phan tihc thi truogn",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        # Transposed typos cannot be matched deterministically; semantic
        # classification is now legitimately reachable. Guard against loops:
        # at most ONE classification call per route().
        self.assertLessEqual(
            self.semantic_gateway.classify_call_count,
            1,
            "[CASE C] more than one model classification call for a single route() "
            "(recursion/duplicate-call defect)",
        )

    # ------------------------------------------------------------------
    # CASE D — common abbreviation
    # ------------------------------------------------------------------

    def test_case_d_abbreviation_mkt_strategy(self) -> None:
        self._assert_desired_intent(
            "D",
            self.router_semantic,
            "lap chien luoc mkt",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        self.assertEqual(
            self.semantic_gateway.classify_call_count,
            0,
            "[CASE D] model fallback unreachable: short-query gate intercepted first",
        )

    # ------------------------------------------------------------------
    # CASE E — no-diacritic competitor research
    # ------------------------------------------------------------------

    def test_case_e_no_accent_competitor_research(self) -> None:
        self._assert_desired_intent(
            "E",
            self.router_semantic,
            "nghien cuu doi thu",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        self.assertEqual(
            self.semantic_gateway.classify_call_count,
            0,
            "[CASE E] model fallback unreachable: short-query gate intercepted first",
        )

    # ------------------------------------------------------------------
    # CASE F — telex-like noisy input
    # ------------------------------------------------------------------

    def test_case_f_telex_noise_marketing(self) -> None:
        self._assert_desired_intent(
            "F",
            self.router_semantic,
            "tooi muoons phaan tichs thij truwowngf",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        # Telex-style noise requires the semantic path; at most ONE
        # classification call per route() (no recursion/duplicate calls).
        self.assertLessEqual(
            self.semantic_gateway.classify_call_count,
            1,
            "[CASE F] more than one model classification call for a single route() "
            "(recursion/duplicate-call defect)",
        )

    def test_case_f_control_long_telex_model_path_reachable(self) -> None:
        """Control: identical noise at >=8 words reaches MODEL_CLASSIFICATION.

        Proves the semantic path itself works and that the defect for short
        messages is purely SHORT_GENERAL_QUERY precedence, not the model.
        """
        long_telex = (
            "tooi muoons phaan tichs thij truwowngf "
            "cho dong san pham moi cua hang chung toi"
        )
        self.assertGreaterEqual(len(long_telex.split()), 8)
        self._assert_desired_intent(
            "F-control",
            self.router_semantic,
            long_telex,
            ConversationIntent.MARKETING_WORKFLOW,
            require_model_consulted=True,
        )

    # ------------------------------------------------------------------
    # CASE G — mixed Vietnamese-English with typos
    # ------------------------------------------------------------------

    def test_case_g_mixed_vietnamese_english_typo_marketing(self) -> None:
        self._assert_desired_intent(
            "G",
            self.router_semantic,
            "phan tihc competitor cho sp nay",
            ConversationIntent.MARKETING_WORKFLOW,
        )
        # Mixed typo + abbreviation requires the semantic path; at most ONE
        # classification call per route() (no recursion/duplicate calls).
        self.assertLessEqual(
            self.semantic_gateway.classify_call_count,
            1,
            "[CASE G] more than one model classification call for a single route() "
            "(recursion/duplicate-call defect)",
        )

    # ------------------------------------------------------------------
    # CASE H — general greeting typo must stay general
    # ------------------------------------------------------------------

    def test_case_h_greeting_typo_remains_general(self) -> None:
        decision = self.router_semantic.route("xin chaof")
        self.assertEqual(
            decision.intent,
            ConversationIntent.GENERAL_CONVERSATION,
            f"[CASE H] greeting typo misrouted; reason_code={decision.reason_code}",
        )

    # ------------------------------------------------------------------
    # CASE I — general question without accents must stay general
    # ------------------------------------------------------------------

    def test_case_i_general_question_no_accents_remains_general(self) -> None:
        decision = self.router_semantic.route("cpa la gi")
        self.assertEqual(
            decision.intent,
            ConversationIntent.GENERAL_CONVERSATION,
            f"[CASE I] general Q&A misrouted; reason_code={decision.reason_code}",
        )

    # ------------------------------------------------------------------
    # CASE J — document intent without accents (no attachment)
    # ------------------------------------------------------------------

    def test_case_j_document_intent_no_diacritics(self) -> None:
        self._assert_desired_intent(
            "J",
            self.router_semantic,
            "tom tat file nay",
            ConversationIntent.DOCUMENT_ANALYSIS,
        )
        self.assertEqual(
            self.semantic_gateway.classify_call_count,
            0,
            "[CASE J] model fallback unreachable: short-query gate intercepted first",
        )

    # ------------------------------------------------------------------
    # CASE K — document intent with typo (no attachment)
    # ------------------------------------------------------------------

    def test_case_k_document_intent_with_typo(self) -> None:
        self._assert_desired_intent(
            "K",
            self.router_semantic,
            "tom tat tai lieu nay ddi",
            ConversationIntent.DOCUMENT_ANALYSIS,
        )
        self.assertEqual(
            self.semantic_gateway.classify_call_count,
            0,
            "[CASE K] model fallback unreachable: short-query gate intercepted first",
        )

    # ------------------------------------------------------------------
    # CASE L — attachment-based routing
    # ------------------------------------------------------------------

    def test_case_l_attachment_basic_document_analysis(self) -> None:
        att = self._make_attachment()
        decision = self.router_plain.route("doc file nay", attachments=[att])
        self.assertEqual(
            decision.intent,
            ConversationIntent.DOCUMENT_ANALYSIS,
            f"[CASE L] attachment routing broke; reason_code={decision.reason_code}",
        )
        self.assertTrue(decision.metadata.get("has_attachments"))

    # ------------------------------------------------------------------
    # CASE M — attachment + noisy marketing intent
    # ------------------------------------------------------------------

    def test_case_m_attachment_plus_noisy_marketing_intent(self) -> None:
        att = self._make_attachment()
        decision = self.router_plain.route(
            "doc file nay roi lap chien luoc mkt",
            attachments=[att],
        )
        self.assertEqual(
            decision.intent,
            ConversationIntent.MARKETING_WORKFLOW,
            f"[CASE M] DOC_AUGUMENTED marketing branch missed noisy intent; "
            f"reason_code={decision.reason_code}; "
            f"root causes={ROOT_CAUSE_MAP.get('M')}",
        )

    # ------------------------------------------------------------------
    # CASE N — short valid marketing command must not be short-circuited
    # ------------------------------------------------------------------

    def test_case_n_short_valid_marketing_not_short_circuited_to_general(self) -> None:
        decision = self.router_plain.route("phan tich thi truong")
        self.assertEqual(
            decision.intent,
            ConversationIntent.MARKETING_WORKFLOW,
            f"[CASE N] short valid marketing command forced to "
            f"{decision.intent.value} via {decision.reason_code}",
        )
        self.assertNotEqual(
            decision.reason_code,
            "SHORT_GENERAL_QUERY",
            f"[CASE N] word-count<8 gate overrode marketing semantics "
            f"(reason_code={decision.reason_code})",
        )

    # ------------------------------------------------------------------
    # CASE O — unknown/random text must remain general (no over-routing)
    # ------------------------------------------------------------------

    def test_case_o_random_unknown_stays_general(self) -> None:
        random_inputs = [
            "blip blop zwip",
            "hay lam dung khong",
            "hom nay troi nang qua",
        ]
        for text in random_inputs:
            with self.subTest(text=text):
                decision = self.router_plain.route(text)
                self.assertEqual(
                    decision.intent,
                    ConversationIntent.GENERAL_CONVERSATION,
                    f"[CASE O] unexpected route for random text "
                    f"(reason_code={decision.reason_code})",
                )

    def test_case_o_guard_no_over_routing_to_marketing(self) -> None:
        """Guard rail for the future fix: tolerant matching must not flip
        clearly non-marketing chatter into MARKETING_WORKFLOW."""
        non_marketing_inputs = [
            "ok",
            "ban co biet cach nau au pho bo ngon nhu cac quan o ha noi khong",
            "toi dang thay buon mot minh buoi chieu nay",
            "cho toi xin loi khuyen ve viec hoc tieng anh moi ngay",
        ]
        for text in non_marketing_inputs:
            with self.subTest(text=text):
                decision = self.router_semantic.route(text)
                self.assertEqual(
                    decision.intent,
                    ConversationIntent.GENERAL_CONVERSATION,
                    f"[CASE O-guard] over-routing detected "
                    f"(reason_code={decision.reason_code})",
                )

    # ------------------------------------------------------------------
    # CASE P — slash command remains SYSTEM_COMMAND
    # ------------------------------------------------------------------

    def test_case_p_slash_command_remains_system_command(self) -> None:
        for text in ["/help", "/export campaign plan"]:
            with self.subTest(text=text):
                decision = self.router_plain.route(text)
                self.assertEqual(
                    decision.intent,
                    ConversationIntent.SYSTEM_COMMAND,
                    f"[CASE P] slash command misrouted "
                    f"(reason_code={decision.reason_code})",
                )
                self.assertEqual(decision.reason_code, "SYSTEM_SLASH_COMMAND")

    # ------------------------------------------------------------------
    # CASE R — raw user text preservation & determinism
    # ------------------------------------------------------------------

    def test_case_r_raw_user_text_preserved_and_deterministic(self) -> None:
        raw = "Phân Tịch Thj Trường !!!"
        att = self._make_attachment(chat_id="CHAT-RAW-1")
        attachments = [att]
        original_content = att.content

        d1 = self.router_semantic.route(raw, attachments=list(attachments))
        d2 = self.router_semantic.route(raw, attachments=list(attachments))

        self.assertEqual(raw, "Phân Tịch Thj Trường !!!")
        self.assertEqual(d1.intent, d2.intent)
        self.assertEqual(d1.reason_code, d2.reason_code)
        self.assertIs(attachments[0], att)
        self.assertEqual(att.content, original_content)
        self.assertNotIn(
            "normalized_text",
            d1.metadata,
            "router must not silently replace the user's raw text",
        )


class TestRoutingFailureSafetyContracts(unittest.TestCase):
    """INPUT-03 failure-safety contracts A-L.

    Narrowly targeted: each test controls ONLY the classifier boundary via a
    mock gateway and verifies a routing contract of the production router.
    """

    def setUp(self) -> None:
        self.att = ChatAttachment(
            chat_id="CHAT-FS-1",
            filename_or_url="brief.pdf",
            attachment_type=AttachmentType.PDF,
            content="Doanh thu Q2 tang 20%.",
        )

    def _stub_router(self) -> tuple:
        gw = SemanticRoutingStubGateway()
        return ConversationRouter(model_gateway=gw), gw

    # A. no gateway + unknown short message -> safe deterministic fallback
    def test_fs_a_no_gateway_short_unknown_safe_fallback(self) -> None:
        router = ConversationRouter(model_gateway=None)
        d = router.route("zwip blip qqq")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertEqual(d.reason_code, "SHORT_GENERAL_QUERY")
        d_long = router.route("hom nay khong co chuyen gi xay ra ca")
        self.assertEqual(d_long.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertEqual(d_long.reason_code, "DEFAULT_GENERAL_FALLBACK")

    # B. classifier raises -> safe fallback, exactly one attempt (no retry)
    def test_fs_b_classifier_exception_single_attempt_then_fallback(self) -> None:
        gw = FailingClassifierGateway()
        router = ConversationRouter(model_gateway=gw)
        d = router.route("phan tihc thi truogn")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertEqual(d.reason_code, "SHORT_GENERAL_QUERY")
        self.assertEqual(
            gw.classify_call_count,
            1,
            "classifier must be attempted exactly once - no retry loop",
        )

    # C. classifier returns garbage -> unparseable answer treated as failure
    def test_fs_c_classifier_garbage_then_fallback(self) -> None:
        gw = GarbageClassifierGateway()
        router = ConversationRouter(model_gateway=gw)
        d = router.route("cpa la gi")
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertEqual(d.reason_code, "SHORT_GENERAL_QUERY")
        self.assertEqual(gw.classify_call_count, 1)

    # D. attachment + classifier failure -> safe document fallback
    def test_fs_d_attachment_classifier_failure_doc_fallback(self) -> None:
        gw = FailingClassifierGateway()
        router = ConversationRouter(model_gateway=gw)
        d = router.route("ban hay xem giup toi voi", attachments=[self.att])
        self.assertEqual(d.intent, ConversationIntent.DOCUMENT_ANALYSIS)
        self.assertEqual(d.reason_code, "ATTACHMENT_DOCUMENT_ANALYSIS")
        self.assertTrue(d.metadata.get("has_attachments"))
        self.assertTrue(d.metadata.get("semantic_fallback"))
        self.assertEqual(gw.classify_call_count, 1)

    # E. attachment + classifier says GENERAL -> safe document fallback
    def test_fs_e_attachment_general_answer_doc_fallback(self) -> None:
        router, gw = self._stub_router()
        d = router.route("ban hay xem giup toi voi", attachments=[self.att])
        self.assertEqual(d.intent, ConversationIntent.DOCUMENT_ANALYSIS)
        self.assertEqual(d.reason_code, "ATTACHMENT_DOCUMENT_ANALYSIS")
        self.assertTrue(d.metadata.get("semantic_fallback"))
        self.assertEqual(gw.classify_call_count, 1)

    # F. attachment + classifier says MARKETING -> marketing workflow
    def test_fs_f_attachment_marketing_via_model(self) -> None:
        router, gw = self._stub_router()
        d = router.route("phan tihc thi truogn tu file nay", attachments=[self.att])
        self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)
        self.assertEqual(d.reason_code, "MODEL_CLASSIFICATION")
        self.assertTrue(d.metadata.get("has_attachments"))
        self.assertEqual(gw.classify_call_count, 1)

    # G. one route() call -> classifier invoked at most once
    def test_fs_g_at_most_one_classifier_call_per_route(self) -> None:
        router, gw = self._stub_router()
        samples = [
            ("xin chaof", None),
            ("cpa la gi", None),
            ("phan tihc competitor cho sp nay", None),
            ("ban hay xem giup toi voi", [self.att]),
            ("Phân tích thị trường", None),
            ("/help", None),
        ]
        for text, atts in samples:
            before = gw.classify_call_count
            router.route(text, attachments=list(atts) if atts else None)
            delta = gw.classify_call_count - before
            self.assertLessEqual(
                delta,
                1,
                f"route() for {text!r} triggered {delta} classification calls",
            )

    # H. raw input unchanged across unicode/noisy samples
    def test_fs_h_raw_input_identity_after_routing(self) -> None:
        router, _ = self._stub_router()
        samples = [
            "Phân Tịch Thj Trường !!!",
            "tooi muoons phaan tichs thij truwowngf",
            "xin chaof",
            "tom tat tai lieu nay ddi",
        ]
        for s in samples:
            router.route(s)
        # The router keeps no per-message state and stores no normalization:
        for s in samples:
            d = router.route(s)
            self.assertNotIn("normalized_text", d.metadata)
        d1 = router.route(samples[0])
        d2 = router.route(samples[0])
        self.assertEqual((d1.intent, d1.reason_code), (d2.intent, d2.reason_code))

    # I. very long normal input -> no truncation/mutation of caller text
    def test_fs_i_long_input_not_truncated_or_mutated(self) -> None:
        router, gw = self._stub_router()
        unit = "tu van hom nay cho toi voi "
        long_text = unit * 400
        expected_len = len(unit) * 400
        d = router.route(long_text)
        self.assertEqual(len(long_text), expected_len)
        self.assertEqual(d.intent, ConversationIntent.GENERAL_CONVERSATION)
        self.assertEqual(gw.classify_call_count, 1)
        # Classification prompt truncates for the MODEL only (pre-existing
        # contract); the caller's string and the recorded payload stay intact.
        self.assertLessEqual(len(gw.classify_calls[0]), 300)
        self.assertEqual(len(long_text), expected_len)

    # J. slash command -> zero semantic classifier calls
    def test_fs_j_slash_command_zero_classifier_calls(self) -> None:
        router, gw = self._stub_router()
        for text in ["/help", "/export campaign plan"]:
            router.route(text)
        self.assertEqual(gw.classify_call_count, 0)

    # K. high-confidence deterministic marketing -> zero classifier calls
    def test_fs_k_deterministic_marketing_zero_classifier_calls(self) -> None:
        router, gw = self._stub_router()
        for text in ["Phân tích thị trường", "lap chien luoc mkt", "nghien cuu doi thu"]:
            d = router.route(text)
            self.assertEqual(d.intent, ConversationIntent.MARKETING_WORKFLOW)
            self.assertEqual(d.reason_code, "DETERMINISTIC_MARKETING_KEYWORD")
        self.assertEqual(gw.classify_call_count, 0)

    # L. high-confidence deterministic document request -> zero classifier calls
    def test_fs_l_deterministic_document_zero_classifier_calls(self) -> None:
        router, gw = self._stub_router()
        d1 = router.route("tom tat file nay")
        self.assertEqual(d1.intent, ConversationIntent.DOCUMENT_ANALYSIS)
        self.assertEqual(d1.reason_code, "DOCUMENT_QUERY_KEYWORDS")
        d2 = router.route("Tóm tắt file này.", attachments=[self.att])
        self.assertEqual(d2.intent, ConversationIntent.DOCUMENT_ANALYSIS)
        self.assertEqual(d2.reason_code, "ATTACHMENT_DOCUMENT_ANALYSIS")
        self.assertEqual(gw.classify_call_count, 0)


if __name__ == "__main__":
    unittest.main()
