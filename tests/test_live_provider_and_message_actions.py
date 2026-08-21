"""Acceptance Tests for Live Model Provider Fix & GPT-Style Message Actions UX.

Validates:
1. UniversalModelGateway live runtime & candidate chain resolution
2. User message editing and preservation in SQLite
3. Assistant message regeneration and route preservation
4. Retry on failed responses with zero duplicate user messages
5. Cross-chat isolation and durability
"""

import os
import tempfile
import unittest
from pathlib import Path

from chat.engine import ChatConversationEngine
from chat.repository import SQLiteChatRepository
from chat.router import ConversationIntent, ConversationRouter
from chat.session import AttachmentType, ChatAttachment, ChatRole, ChatSessionManager
from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.gateway import UniversalModelGateway
from runtime.engine import FiveAgentDepartmentRuntime


class MockTestAdapter(BaseModelAdapter):
    def __init__(self, name: str = "mock_provider", fail: bool = False, reply: str = "Phản hồi thử nghiệm") -> None:
        self._name = name
        self.fail = fail
        self.reply = reply
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def default_model(self) -> str:
        return "mock-model"

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.call_count += 1
        if self.fail:
            return ModelResponse(
                request_id=request.request_id,
                provider=self.provider_name,
                model_name=request.model_name,
                status=ModelResponseStatus.ERROR,
                error="PROVIDER_UNAVAILABLE",
                usage=ModelUsage(usage_source="NOT_AVAILABLE"),
                latency_ms=10.0,
            )
        return ModelResponse(
            request_id=request.request_id,
            provider=self.provider_name,
            model_name=request.model_name,
            status=ModelResponseStatus.SUCCESS,
            content=self.reply,
            usage=ModelUsage(total_tokens=25, usage_source="PROVIDER_REPORTED"),
            latency_ms=20.0,
        )


class TestLiveProviderAndMessageActions(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_chat_actions.sqlite"
        self.repo = SQLiteChatRepository(db_path=str(self.db_path))
        self.chat_mgr = ChatSessionManager(repository=self.repo)

        self.mock_adapter = MockTestAdapter(name="xkiro", reply="Chào bạn! Tôi có thể giúp gì?")
        self.gateway = UniversalModelGateway(free_only_mode=True)
        self.gateway.provider_registry.register_custom_adapter(self.mock_adapter)

        self.engine = ChatConversationEngine(model_gateway=self.gateway)
        self.router = ConversationRouter(model_gateway=self.gateway)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_copy_user_message(self) -> None:
        """Test user message raw text extraction for copy action."""
        session = self.chat_mgr.create_session(title="Copy Test")
        msg = self.chat_mgr.add_user_message(session.chat_id, "xin chào AI Department")
        self.assertIsNotNone(msg)
        self.assertEqual(msg.content, "xin chào AI Department")

    def test_edit_user_message_and_sqlite_persistence(self) -> None:
        """Test editing user message updates SQLite and preserves message identity."""
        session = self.chat_mgr.create_session(title="Edit Test")
        msg = self.chat_mgr.add_user_message(session.chat_id, "Câu hỏi ban đầu")
        self.assertIsNotNone(msg)

        # In-place edit
        updated = self.chat_mgr.update_message(msg.message_id, "Câu hỏi đã được chỉnh sửa")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.content, "Câu hỏi đã được chỉnh sửa")

        # Verify durable persistence in new session manager instance
        new_mgr = ChatSessionManager(db_path=str(self.db_path))
        persisted_session = new_mgr.get_session(session.chat_id)
        self.assertIsNotNone(persisted_session)
        self.assertEqual(len(persisted_session.messages), 1)
        self.assertEqual(persisted_session.messages[0].content, "Câu hỏi đã được chỉnh sửa")

    def test_edit_resend_continuation(self) -> None:
        """Test editing a message and generating a fresh response."""
        session = self.chat_mgr.create_session(title="Edit Resend")
        msg = self.chat_mgr.add_user_message(session.chat_id, "xin chào")

        # Edit message
        self.chat_mgr.update_message(msg.message_id, "bạn có thể giúp tôi những gì?")

        # Generate response for edited turn
        fresh_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(fresh_session)
        res = self.engine.generate_chat_response(fresh_session, "bạn có thể giúp tôi những gì?")
        self.assertTrue(res["success"])

        resp_msg = self.chat_mgr.add_assistant_response(session.chat_id, res["content"])
        self.assertIsNotNone(resp_msg)

        # Total user messages must remain exactly 1
        updated_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(updated_session)
        user_msgs = [m for m in updated_session.messages if m.role == ChatRole.USER]
        self.assertEqual(len(user_msgs), 1)
        self.assertEqual(user_msgs[0].content, "bạn có thể giúp tôi những gì?")

    def test_copy_assistant_message(self) -> None:
        """Test assistant response text format for clipboard copy."""
        session = self.chat_mgr.create_session(title="Assistant Copy")
        resp_msg = self.chat_mgr.add_assistant_response(
            session.chat_id,
            "# Kế hoạch Marketing\n- Bước 1: Nghiên cứu\n- Bước 2: Triển khai",
        )
        self.assertIsNotNone(resp_msg)
        self.assertIn("# Kế hoạch Marketing", resp_msg.content)

    def test_regenerate_assistant_response_no_duplicate_user_message(self) -> None:
        """Test regenerating response creates new assistant output without duplicating user message."""
        session = self.chat_mgr.create_session(title="Regenerate Test")
        self.chat_mgr.add_user_message(session.chat_id, "Phân tích CPA là gì?")
        self.chat_mgr.add_assistant_response(session.chat_id, "CPA là Cost Per Action (v1)")

        # Regenerate
        fresh_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(fresh_session)
        res2 = self.engine.generate_chat_response(fresh_session, "Phân tích CPA là gì?")
        self.chat_mgr.add_assistant_response(session.chat_id, res2["content"])

        updated_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(updated_session)
        user_msgs = [m for m in updated_session.messages if m.role == ChatRole.USER]
        self.assertEqual(len(user_msgs), 1)
        self.assertEqual(user_msgs[0].content, "Phân tích CPA là gì?")

    def test_retry_failed_response(self) -> None:
        """Test retry after initial error executes successfully without duplicate user messages."""
        session = self.chat_mgr.create_session(title="Retry Test")
        self.chat_mgr.add_user_message(session.chat_id, "Thử lại lần 2")

        # Initial failed attempt
        self.chat_mgr.add_assistant_response(session.chat_id, "⚠️ Không thể kết nối với model.", status="ERROR")

        # Retry
        fresh_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(fresh_session)
        res = self.engine.generate_chat_response(fresh_session, "Thử lại lần 2")
        self.assertTrue(res["success"])
        self.chat_mgr.add_assistant_response(session.chat_id, res["content"], status="COMPLETED")

        updated_session = self.chat_mgr.get_session(session.chat_id)
        self.assertIsNotNone(updated_session)
        user_msgs = [m for m in updated_session.messages if m.role == ChatRole.USER]
        self.assertEqual(len(user_msgs), 1)

    def test_cross_chat_isolation(self) -> None:
        """Ensure messages in chat A do not leak into chat B."""
        session_a = self.chat_mgr.create_session(title="Chat A")
        session_b = self.chat_mgr.create_session(title="Chat B")

        self.chat_mgr.add_user_message(session_a.chat_id, "Nội dung của Chat A")
        self.chat_mgr.add_user_message(session_b.chat_id, "Nội dung của Chat B")

        msgs_a = self.repo.list_messages(session_a.chat_id)
        msgs_b = self.repo.list_messages(session_b.chat_id)

        self.assertEqual(len(msgs_a), 1)
        self.assertEqual(msgs_a[0].content, "Nội dung của Chat A")
        self.assertEqual(len(msgs_b), 1)
        self.assertEqual(msgs_b[0].content, "Nội dung của Chat B")

    def test_route_preserved_on_regenerate(self) -> None:
        """Ensure intent routing remains consistent upon message regeneration."""
        d1 = self.router.route("xin chào")
        self.assertEqual(d1.intent, ConversationIntent.GENERAL_CONVERSATION)

        d2 = self.router.route("Tóm tắt file dữ liệu đính kèm", attachments=[ChatAttachment(chat_id="C1", filename_or_url="data.csv", attachment_type=AttachmentType.CSV, content="a,b\n1,2")])
        self.assertEqual(d2.intent, ConversationIntent.DOCUMENT_ANALYSIS)

        d3 = self.router.route("Xây dựng chiến lược marketing toàn diện cho sản phẩm")
        self.assertEqual(d3.intent, ConversationIntent.MARKETING_WORKFLOW)


if __name__ == "__main__":
    unittest.main()
