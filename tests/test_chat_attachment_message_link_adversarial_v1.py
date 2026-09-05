"""Adversarial regression for durable attachment-to-message ownership.

Production invariant:
- chat-level attachment inventory may contain every attachment in the session;
- each ChatMessage must hydrate only the attachments that were submitted with
  that exact message;
- standalone/session attachments must never be smeared onto user messages;
- the invariant must survive repository/process-style recreation.
"""

import os
import shutil
import tempfile
import unittest

from chat.repository import SQLiteChatRepository
from chat.session import AttachmentType, ChatAttachment, ChatRole, ChatSessionManager


class TestChatAttachmentMessageLinkAdversarialV1(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "chat_attachment_message_link.sqlite")
        self.repo = SQLiteChatRepository(db_path=self.db_path)
        self.manager = ChatSessionManager(repository=self.repo)

    def tearDown(self) -> None:
        self.repo.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _attachment(self, chat_id: str, name: str, content: str) -> ChatAttachment:
        return ChatAttachment(
            chat_id=chat_id,
            filename_or_url=name,
            attachment_type=AttachmentType.TEXT,
            content=content,
        )

    def test_restart_preserves_exact_attachment_ownership_per_message(self) -> None:
        session = self.manager.create_session(title="Attachment ownership")

        first_attachment = self._attachment(session.chat_id, "first.txt", "FIRST-ONLY")
        first_message = self.manager.add_user_message(
            session.chat_id,
            "first turn",
            attachments=[first_attachment],
        )
        self.manager.add_assistant_response(session.chat_id, "first response")

        second_attachment = self._attachment(session.chat_id, "second.txt", "SECOND-ONLY")
        second_message = self.manager.add_user_message(
            session.chat_id,
            "second turn",
            attachments=[second_attachment],
        )

        self.assertIsNotNone(first_message)
        self.assertIsNotNone(second_message)
        self.repo.close()

        restarted_repo = SQLiteChatRepository(db_path=self.db_path)
        try:
            restarted_manager = ChatSessionManager(repository=restarted_repo)
            loaded = restarted_manager.get_session(session.chat_id)
            self.assertIsNotNone(loaded)

            user_messages = {
                message.message_id: message
                for message in loaded.messages
                if message.role == ChatRole.USER
            }
            self.assertEqual(set(user_messages), {first_message.message_id, second_message.message_id})

            self.assertEqual(
                [a.attachment_id for a in user_messages[first_message.message_id].attachments],
                [first_attachment.attachment_id],
                "First message received attachments owned by another turn.",
            )
            self.assertEqual(
                [a.attachment_id for a in user_messages[second_message.message_id].attachments],
                [second_attachment.attachment_id],
                "Second message received attachments owned by another turn.",
            )

            # Direct message lookup must obey the same ownership boundary.
            loaded_first = restarted_repo.get_message(first_message.message_id)
            loaded_second = restarted_repo.get_message(second_message.message_id)
            self.assertEqual([a.attachment_id for a in loaded_first.attachments], [first_attachment.attachment_id])
            self.assertEqual([a.attachment_id for a in loaded_second.attachments], [second_attachment.attachment_id])

            # Session inventory still contains both attachments exactly once.
            self.assertEqual(
                {a.attachment_id for a in loaded.attachments},
                {first_attachment.attachment_id, second_attachment.attachment_id},
            )
        finally:
            restarted_repo.close()

    def test_standalone_session_attachment_is_not_assigned_to_user_messages(self) -> None:
        session = self.manager.create_session(title="Standalone attachment")
        message = self.manager.add_user_message(session.chat_id, "message without file")
        standalone = self._attachment(session.chat_id, "session-note.txt", "SESSION-LEVEL")
        self.manager.add_attachment(standalone)
        self.repo.close()

        restarted_repo = SQLiteChatRepository(db_path=self.db_path)
        try:
            loaded_message = restarted_repo.get_message(message.message_id)
            self.assertEqual(
                loaded_message.attachments,
                [],
                "A standalone session attachment was incorrectly assigned to a user message.",
            )
            self.assertEqual(
                [a.attachment_id for a in restarted_repo.list_attachments(session.chat_id)],
                [standalone.attachment_id],
            )
        finally:
            restarted_repo.close()


if __name__ == "__main__":
    unittest.main()
