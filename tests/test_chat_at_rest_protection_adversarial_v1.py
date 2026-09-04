"""Adversarial RED regression for chat/attachment at-rest protection.

Production SQLite persistence must not expose user/agent payload plaintext in
raw persisted columns. Public repository reads must still round-trip the
original values across a fresh repository instance.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from chat.repository import SQLiteChatRepository
from chat.session import AttachmentType, ChatAttachment, ChatSessionManager


class TestChatAtRestProtectionAdversarialV1(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "chat_at_rest.sqlite")
        self.repo = SQLiteChatRepository(db_path=self.db_path)
        self.chat_mgr = ChatSessionManager(repository=self.repo)

    def tearDown(self) -> None:
        self.repo.close()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sensitive_chat_payloads_are_not_plaintext_at_rest_and_restart_round_trip(self) -> None:
        message_secret = "CHAT_AT_REST_MESSAGE_SECRET_7F2B9D"
        assistant_secret = "CHAT_AT_REST_ASSISTANT_SECRET_A18C44"
        agent_output_secret = "CHAT_AT_REST_AGENT_OUTPUT_SECRET_5C901E"
        attachment_secret = "CHAT_AT_REST_ATTACHMENT_SECRET_D47A11"

        session = self.chat_mgr.create_session(title="At-rest protection regression")
        attachment = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url="private.txt",
            attachment_type=AttachmentType.TEXT,
            content=attachment_secret,
        )
        self.chat_mgr.add_user_message(
            session.chat_id,
            message_secret,
            attachments=[attachment],
        )
        self.chat_mgr.add_assistant_response(
            session.chat_id,
            assistant_secret,
            agent_outputs={"private_evidence": agent_output_secret},
        )

        # Read the physical SQLite values directly, bypassing repository decode.
        # A protected store may contain opaque ciphertext/encoded envelopes, but
        # never the original sensitive payload plaintext.
        with sqlite3.connect(self.db_path) as conn:
            raw_message_rows = conn.execute(
                "SELECT content, agent_outputs_json FROM chat_messages WHERE chat_id = ? ORDER BY sequence_number",
                (session.chat_id,),
            ).fetchall()
            raw_attachment_rows = conn.execute(
                "SELECT content FROM chat_attachments WHERE chat_id = ?",
                (session.chat_id,),
            ).fetchall()
            raw_preview = conn.execute(
                "SELECT last_message_preview FROM chat_sessions WHERE chat_id = ?",
                (session.chat_id,),
            ).fetchone()[0]

        raw_message_text = json.dumps(raw_message_rows, ensure_ascii=False)
        raw_attachment_text = json.dumps(raw_attachment_rows, ensure_ascii=False)

        self.assertNotIn(
            message_secret,
            raw_message_text,
            "User message plaintext must not be persisted in raw SQLite columns.",
        )
        self.assertNotIn(
            assistant_secret,
            raw_message_text,
            "Assistant message plaintext must not be persisted in raw SQLite columns.",
        )
        self.assertNotIn(
            agent_output_secret,
            raw_message_text,
            "Agent output plaintext must not be persisted in raw SQLite columns.",
        )
        self.assertNotIn(
            attachment_secret,
            raw_attachment_text,
            "Attachment content plaintext must not be persisted in raw SQLite columns.",
        )
        self.assertNotIn(
            assistant_secret,
            raw_preview,
            "Last-message preview must not duplicate sensitive message plaintext at rest.",
        )

        # Protection is a storage boundary only: callers still receive the
        # original logical values after a fresh repository instance/restart.
        self.repo.close()
        restarted_repo = SQLiteChatRepository(db_path=self.db_path)
        try:
            restarted = restarted_repo.get_session(session.chat_id)
            self.assertIsNotNone(restarted)
            self.assertEqual(restarted.messages[0].content, message_secret)
            self.assertEqual(restarted.messages[1].content, assistant_secret)
            self.assertEqual(
                restarted.messages[1].agent_outputs.get("private_evidence"),
                agent_output_secret,
            )
            self.assertEqual(restarted.attachments[0].content, attachment_secret)
            self.assertEqual(restarted.last_message_preview, assistant_secret)
        finally:
            restarted_repo.close()


if __name__ == "__main__":
    unittest.main()
