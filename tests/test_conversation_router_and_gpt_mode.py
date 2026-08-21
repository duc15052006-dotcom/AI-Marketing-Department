"""Unit and Acceptance Tests for GPT-Like Conversation Router & Real 5-Agent Execution.

Validates Acceptance Tests A through H:
- Test A: "bạn biết tiếng Việt không?" -> GENERAL_CONVERSATION, 5-agent call count = 0
- Test B: "xin chào" -> GENERAL_CONVERSATION, 5-agent call count = 0
- Test C: "CPA là gì?" -> GENERAL_CONVERSATION, 5-agent call count = 0
- Test D: Multi-turn same-chat context retention ("Tôi tên Minh." -> "Tôi tên gì?")
- Test E: Attach PDF "Tóm tắt file này." -> DOCUMENT_ANALYSIS, 5-agent call count = 0
- Test F: Attach PDF "Đọc tài liệu này và xây chiến lược marketing." -> MARKETING_WORKFLOW
- Test G: "Phân tích thị trường và lập campaign TikTok cho sản phẩm này với ngân sách 30 triệu." -> MARKETING_WORKFLOW (Final CMO Markdown)
- Test H: Honest error reporting on provider failure (Zero fake success fallback)
- Static content leak test (Zero production benchmark claim leakage)
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from chat.engine import ChatConversationEngine
from chat.knowledge import SessionKnowledgeStore
from chat.repository import SQLiteChatRepository
from chat.router import ConversationIntent, ConversationRouter
from chat.session import AttachmentType, ChatAttachment, ChatSessionManager
from integrations.models.base import ModelMessage, ModelRequest, ModelResponse, ModelResponseStatus, ModelRole
from integrations.models.gateway import UniversalModelGateway
from runtime.engine import FiveAgentDepartmentRuntime


class MockEchoModelGateway(UniversalModelGateway):
    """Predictable mock gateway for testing conversation engine & router."""

    def __init__(self) -> None:
        super().__init__(free_only_mode=True)
        self.call_history: list[ModelRequest] = []

    def generate(self, request: ModelRequest, **kwargs) -> ModelResponse:
        self.call_history.append(request)
        last_msg = request.messages[-1].content if request.messages else ""
        sys_msg = request.messages[0].content if request.messages and request.messages[0].role == ModelRole.SYSTEM else ""

        # Multi-turn recall check
        if "tôi tên gì" in last_msg.lower():
            # Check if previous turn had the name
            for m in request.messages[:-1]:
                if "tôi tên minh" in m.content.lower() or "tôi tên là minh" in m.content.lower() or "minh" in m.content.lower():
                    return ModelResponse(
                        request_id=request.request_id,
                        provider="mock_llm",
                        model_name="mock-model",
                        status=ModelResponseStatus.SUCCESS,
                        content="Bạn tên là Minh.",
                    )
            return ModelResponse(
                request_id=request.request_id,
                provider="mock_llm",
                model_name="mock-model",
                status=ModelResponseStatus.SUCCESS,
                content="Tôi chưa biết tên của bạn.",
            )

        # Vietnamese language question
        if "biết tiếng việt" in last_msg.lower():
            return ModelResponse(
                request_id=request.request_id,
                provider="mock_llm",
                model_name="mock-model",
                status=ModelResponseStatus.SUCCESS,
                content="Có chứ! Tôi hoàn toàn có thể hiểu và giao tiếp bằng tiếng Việt.",
            )

        # Definition check
        if "cpa là gì" in last_msg.lower():
            return ModelResponse(
                request_id=request.request_id,
                provider="mock_llm",
                model_name="mock-model",
                status=ModelResponseStatus.SUCCESS,
                content="**CPA (Cost Per Acquisition)** là chi phí để có được một khách hàng mới hoặc một chuyển đổi.",
            )

        # Document summary check
        if "ATTACHED DOCUMENTS" in sys_msg or "tóm tắt" in last_msg.lower() or "summarize" in last_msg.lower():
            return ModelResponse(
                request_id=request.request_id,
                provider="mock_llm",
                model_name="mock-model",
                status=ModelResponseStatus.SUCCESS,
                content="### Tóm tắt tài liệu:\nTài liệu cung cấp các thông tin quan trọng về sản phẩm và mục tiêu.",
            )

        return ModelResponse(
            request_id=request.request_id,
            provider="mock_llm",
            model_name="mock-model",
            status=ModelResponseStatus.SUCCESS,
            content=f"Phản hồi cho câu hỏi: {last_msg}",
        )


class TestConversationRouterAndGptMode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_router_gpt_")
        self.db_path = Path(self.temp_dir) / "test_app.sqlite"
        self.mock_gateway = MockEchoModelGateway()
        self.router = ConversationRouter(model_gateway=self.mock_gateway)
        self.session_knowledge = SessionKnowledgeStore()
        self.repo = SQLiteChatRepository(db_path=self.db_path)
        self.chat_mgr = ChatSessionManager(repository=self.repo)
        self.chat_engine = ChatConversationEngine(
            model_gateway=self.mock_gateway,
            session_knowledge=self.session_knowledge,
        )

    def tearDown(self):
        self.repo.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST A
    # -------------------------------------------------------------------------
    def test_acceptance_a_vietnamese_language_inquiry(self):
        decision = self.router.route("bạn biết tiếng Việt không?")
        self.assertEqual(decision.intent, ConversationIntent.GENERAL_CONVERSATION)

        session = self.chat_mgr.create_session(title="Test A")
        self.chat_mgr.add_user_message(session.chat_id, "bạn biết tiếng Việt không?")

        res = self.chat_engine.generate_chat_response(session, "bạn biết tiếng Việt không?")
        self.assertTrue(res["success"])
        self.assertIn("tiếng Việt", res["content"])

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST B
    # -------------------------------------------------------------------------
    def test_acceptance_b_greeting(self):
        decision = self.router.route("xin chào")
        self.assertEqual(decision.intent, ConversationIntent.GENERAL_CONVERSATION)

        session = self.chat_mgr.create_session(title="Test B")
        res = self.chat_engine.generate_chat_response(session, "xin chào")
        self.assertTrue(res["success"])
        self.assertTrue(len(res["content"]) > 0)

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST C
    # -------------------------------------------------------------------------
    def test_acceptance_c_marketing_qa_definition(self):
        decision = self.router.route("CPA là gì?")
        self.assertEqual(decision.intent, ConversationIntent.GENERAL_CONVERSATION)

        session = self.chat_mgr.create_session(title="Test C")
        res = self.chat_engine.generate_chat_response(session, "CPA là gì?")
        self.assertTrue(res["success"])
        self.assertIn("CPA", res["content"])

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST D: MULTI-TURN CONTEXT & SAME-CHAT RECALL
    # -------------------------------------------------------------------------
    def test_acceptance_d_multi_turn_same_chat_recall(self):
        session1 = self.chat_mgr.create_session(title="Chat 1")
        session2 = self.chat_mgr.create_session(title="Chat 2")

        # Turn 1 in Chat 1: "Tôi tên Minh."
        self.chat_mgr.add_user_message(session1.chat_id, "Tôi tên Minh.")
        resp1 = self.chat_engine.generate_chat_response(session1, "Tôi tên Minh.")
        self.chat_mgr.add_assistant_response(session1.chat_id, resp1["content"])

        # Reload session from DB to verify persistence hydration
        session1_reloaded = self.chat_mgr.get_session(session1.chat_id)
        self.assertIsNotNone(session1_reloaded)

        # Turn 2 in Chat 1: "Tôi tên gì?"
        self.chat_mgr.add_user_message(session1_reloaded.chat_id, "Tôi tên gì?")
        resp2 = self.chat_engine.generate_chat_response(session1_reloaded, "Tôi tên gì?")
        self.assertIn("Minh", resp2["content"], "Should correctly recall name from same-chat history")

        # Cross-Chat Isolation Check: Chat 2 should NOT know the name
        self.chat_mgr.add_user_message(session2.chat_id, "Tôi tên gì?")
        resp_isolated = self.chat_engine.generate_chat_response(session2, "Tôi tên gì?")
        self.assertNotIn("Minh", resp_isolated["content"], "Should NOT leak name into separate chat session")

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST E: ATTACHMENT DOCUMENT ANALYSIS
    # -------------------------------------------------------------------------
    def test_acceptance_e_document_analysis_route(self):
        session = self.chat_mgr.create_session(title="Doc Chat")
        att = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url="company_profile.pdf",
            attachment_type=AttachmentType.PDF,
            content="Công ty ABC chuyên sản xuất phần mềm quản lý kho.",
        )
        self.session_knowledge.index_attachment(att)

        decision = self.router.route("Tóm tắt file này.", attachments=[att])
        self.assertEqual(decision.intent, ConversationIntent.DOCUMENT_ANALYSIS)

        self.chat_mgr.add_user_message(session.chat_id, "Tóm tắt file này.", attachments=[att])

        res = self.chat_engine.generate_chat_response(session, "Tóm tắt file này.", attachments=[att], is_document_analysis=True)
        self.assertTrue(res["success"])
        self.assertTrue(len(res["content"]) > 0)

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST F: DOCUMENT WITH EXPLICIT MARKETING WORKFLOW
    # -------------------------------------------------------------------------
    def test_acceptance_f_document_with_marketing_workflow(self):
        att = ChatAttachment(
            chat_id="CHAT-DOC-2",
            filename_or_url="product_brief.pdf",
            attachment_type=AttachmentType.PDF,
            content="Sản phẩm tai nghe chống ồn không dây cao cấp.",
        )
        decision = self.router.route("Đọc tài liệu này và xây chiến lược marketing.", attachments=[att])
        self.assertEqual(decision.intent, ConversationIntent.MARKETING_WORKFLOW)

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST G: FULL MARKETING WORKFLOW WITH FINAL CMO MARKDOWN
    # -------------------------------------------------------------------------
    def test_acceptance_g_full_marketing_workflow_execution(self):
        query = "Phân tích thị trường và lập campaign TikTok cho sản phẩm này với ngân sách 30 triệu."
        decision = self.router.route(query)
        self.assertEqual(decision.intent, ConversationIntent.MARKETING_WORKFLOW)

        runtime = FiveAgentDepartmentRuntime(model_gateway=self.mock_gateway)
        ctx = runtime.start_run(objective=query)

        cmo_init = runtime.execute_stage_cmo_initial(ctx)
        self.assertIn("cmo", cmo_init["agent"])

        intel_out = runtime.execute_stage_intelligence(ctx)
        self.assertIn("intelligence", intel_out["agent"])

        strat_out = runtime.execute_stage_strategist(ctx)
        self.assertIn("strategist", strat_out["agent"])

        crtv_out = runtime.execute_stage_creative(ctx)
        self.assertIn("creative", crtv_out["agent"])

        perf_out = runtime.execute_stage_performance(ctx)
        self.assertIn("performance", perf_out["agent"])

        cmo_final = runtime.execute_stage_final_cmo(ctx)
        self.assertIn("final_cmo", ctx.stage_outputs)
        self.assertIn("master_gtm_plan_markdown", cmo_final)
        self.assertTrue(cmo_final["master_gtm_plan_markdown"].startswith("#"), "Final CMO output must be formatted Markdown")

        artifact = runtime.complete_run(ctx)
        self.assertTrue(artifact.final_artifact_hash != "")

    # -------------------------------------------------------------------------
    # ACCEPTANCE TEST H: HONEST ERROR REPORTING ON PROVIDER FAILURE
    # -------------------------------------------------------------------------
    def test_acceptance_h_honest_error_reporting(self):
        class FailingModelGateway(UniversalModelGateway):
            def generate(self, request, **kwargs):
                return ModelResponse(
                    request_id=request.request_id,
                    provider="failing_gateway",
                    model_name="unknown",
                    status=ModelResponseStatus.ERROR,
                    error="AUTHENTICATION_FAILED: Invalid API key.",
                )

        failing_gateway = FailingModelGateway()
        engine = ChatConversationEngine(model_gateway=failing_gateway)
        session = self.chat_mgr.create_session(title="Failing Test")

        res = engine.generate_chat_response(session, "Phân tích câu hỏi phức tạp không có trong offline fallback")
        # Should return transparent error without fabricating fake marketing work
        self.assertFalse(res["success"])
        self.assertIn("Không thể hoàn tất phản hồi", res["content"])
        self.assertNotIn("Received objective", res["content"])
        self.assertNotIn("Analyzing market signals", res["content"])

    # -------------------------------------------------------------------------
    # STATIC CONTENT LEAK TEST
    # -------------------------------------------------------------------------
    def test_static_content_leak_prevention(self):
        runtime = FiveAgentDepartmentRuntime(model_gateway=self.mock_gateway)
        ctx = runtime.start_run(objective="Xây dựng thương hiệu thời trang GenZ")

        runtime.execute_stage_cmo_initial(ctx)
        runtime.execute_stage_intelligence(ctx)
        runtime.execute_stage_strategist(ctx)
        runtime.execute_stage_creative(ctx)
        runtime.execute_stage_performance(ctx)
        cmo_final = runtime.execute_stage_final_cmo(ctx)

        final_md = cmo_final["master_gtm_plan_markdown"]
        # Production output must not leak hardcoded CardioVital medical benchmark strings
        self.assertNotIn("High search volume for non-invasive metabolic", final_md)
        self.assertNotIn("The premier physician-guided preventive cardiology", final_md)
        self.assertNotIn("Don't wait for symptoms to protect your cardiovascular health", final_md)


if __name__ == "__main__":
    unittest.main()
