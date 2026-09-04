"""Adversarial regression for chat/attachment at-rest protection.

The production repository must never persist sensitive chat payload plaintext.
Tests inject a deterministic non-production codec so repository wiring and
migration semantics can be exercised on any CI platform. Production still uses
its OS-backed protector by default; this test double is never auto-selected.
"""

import base64
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from chat.repository import ChatPayloadProtector, SQLiteChatRepository
from chat.session import AttachmentType, ChatAttachment, ChatSessionManager


class _TestPayloadProtector(ChatPayloadProtector):
    """Explicit TEST-ONLY reversible codec; not production encryption."""

    PREFIX = "TEST1:"

    def protect_text(self, value: str) -> str:
        encoded = base64.b64encode(str(value).encode("utf-8")).decode("ascii")
        return self.PREFIX + encoded

    def unprotect_text(self, persisted_value: str) -> str:
        raw = str(persisted_value)
        if not raw.startswith(self.PREFIX):
            raise ValueError("test payload is not protected")
        return base64.b64decode(raw[len(self.PREFIX):], validate=True).decode("utf-8")


class _FailingPayloadProtector(_TestPayloadProtector):
    """Fails during migration to prove the persistence transaction rolls back."""

    def __init__(self, fail_after: int = 1) -> None:
        self.calls = 0
        self.fail_after = fail_after

    def protect_text(self, value: str) -> str:
        self.calls += 1
        if self.calls > self.fail_after:
            raise RuntimeError("INJECTED_PAYLOAD_PROTECTION_FAILURE")
        return super().protect_text(value)


class TestChatAtRestProtectionAdversarialV1(unittest.TestCase):
    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "chat_at_rest.sqlite")
        self.protector = _TestPayloadProtector()

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @staticmethod
    def _create_legacy_v1_database(db_path: str, sentinels: dict) -> str:
        """Create the exact sensitive v1 column shape with plaintext legacy rows."""
        now = datetime.now(timezone.utc).isoformat()
        chat_id = "CHAT-LEGACY01"
        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE chat_sessions (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'ACTIVE',
                    project_id TEXT,
                    business_id TEXT,
                    archived INTEGER NOT NULL DEFAULT 0,
                    last_message_preview TEXT NOT NULL DEFAULT '',
                    last_run_id TEXT
                );
                CREATE TABLE chat_messages (
                    message_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    sender_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    run_id TEXT,
                    status TEXT NOT NULL DEFAULT 'COMPLETED',
                    sequence_number INTEGER NOT NULL DEFAULT 0,
                    agent_outputs_json TEXT,
                    FOREIGN KEY(chat_id) REFERENCES chat_sessions(chat_id) ON DELETE CASCADE
                );
                CREATE TABLE chat_attachments (
                    attachment_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'INLINE_UPLOAD',
                    local_storage_ref TEXT,
                    created_at TEXT NOT NULL,
                    parser_status TEXT NOT NULL DEFAULT 'PARSED',
                    content_size_bytes INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(chat_id) REFERENCES chat_sessions(chat_id) ON DELETE CASCADE
                );
                """
            )
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (1, now),
            )
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    chat_id, title, created_at, updated_at, status,
                    project_id, business_id, archived, last_message_preview, last_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    "Legacy at-rest migration",
                    now,
                    now,
                    "ACTIVE",
                    "PROJECT-LEGACY",
                    "BUSINESS-LEGACY",
                    0,
                    sentinels["preview"],
                    None,
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    message_id, chat_id, role, sender_name, content,
                    created_at, run_id, status, sequence_number, agent_outputs_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "MSG-LEGACY01",
                    chat_id,
                    "assistant",
                    "Five-Agent Department",
                    sentinels["message"],
                    now,
                    None,
                    "COMPLETED",
                    0,
                    json.dumps({"private_evidence": sentinels["agent_output"]}),
                ),
            )
            conn.execute(
                """
                INSERT INTO chat_attachments (
                    attachment_id, chat_id, filename, media_type, content,
                    content_hash, source_type, local_storage_ref, created_at,
                    parser_status, content_size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "ATT-LEGACY01",
                    chat_id,
                    "legacy-private.txt",
                    "text",
                    sentinels["attachment"],
                    "legacy-content-hash",
                    "INLINE_UPLOAD",
                    None,
                    now,
                    "PARSED",
                    len(sentinels["attachment"].encode("utf-8")),
                ),
            )
            conn.commit()
        return chat_id

    @staticmethod
    def _raw_sensitive_values(db_path: str, chat_id: str) -> tuple:
        with sqlite3.connect(db_path) as conn:
            raw_message_rows = conn.execute(
                "SELECT content, agent_outputs_json FROM chat_messages WHERE chat_id = ? ORDER BY sequence_number",
                (chat_id,),
            ).fetchall()
            raw_attachment_rows = conn.execute(
                "SELECT content FROM chat_attachments WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
            raw_preview = conn.execute(
                "SELECT last_message_preview FROM chat_sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()[0]
        return raw_message_rows, raw_attachment_rows, raw_preview

    def test_sensitive_chat_payloads_are_not_plaintext_at_rest_and_restart_round_trip(self) -> None:
        message_secret = "CHAT_AT_REST_MESSAGE_SECRET_7F2B9D"
        assistant_secret = "CHAT_AT_REST_ASSISTANT_SECRET_A18C44"
        agent_output_secret = "CHAT_AT_REST_AGENT_OUTPUT_SECRET_5C901E"
        attachment_secret = "CHAT_AT_REST_ATTACHMENT_SECRET_D47A11"

        repo = SQLiteChatRepository(
            db_path=self.db_path,
            payload_protector=self.protector,
        )
        chat_mgr = ChatSessionManager(repository=repo)
        session = chat_mgr.create_session(title="At-rest protection regression")
        attachment = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url="private.txt",
            attachment_type=AttachmentType.TEXT,
            content=attachment_secret,
        )
        chat_mgr.add_user_message(
            session.chat_id,
            message_secret,
            attachments=[attachment],
        )
        chat_mgr.add_assistant_response(
            session.chat_id,
            assistant_secret,
            agent_outputs={"private_evidence": agent_output_secret},
        )

        raw_message_rows, raw_attachment_rows, raw_preview = self._raw_sensitive_values(
            self.db_path, session.chat_id
        )
        raw_message_text = json.dumps(raw_message_rows, ensure_ascii=False)
        raw_attachment_text = json.dumps(raw_attachment_rows, ensure_ascii=False)

        self.assertNotIn(message_secret, raw_message_text)
        self.assertNotIn(assistant_secret, raw_message_text)
        self.assertNotIn(agent_output_secret, raw_message_text)
        self.assertNotIn(attachment_secret, raw_attachment_text)
        self.assertNotIn(assistant_secret, raw_preview)

        repo.close()
        restarted_repo = SQLiteChatRepository(
            db_path=self.db_path,
            payload_protector=_TestPayloadProtector(),
        )
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

    def test_schema_v1_plaintext_payloads_are_migrated_and_round_trip(self) -> None:
        sentinels = {
            "preview": "LEGACY_PREVIEW_SECRET_1D2A",
            "message": "LEGACY_MESSAGE_SECRET_2E3B",
            "agent_output": "LEGACY_AGENT_OUTPUT_SECRET_3F4C",
            "attachment": "LEGACY_ATTACHMENT_SECRET_4A5D",
        }
        chat_id = self._create_legacy_v1_database(self.db_path, sentinels)

        repo = SQLiteChatRepository(
            db_path=self.db_path,
            payload_protector=self.protector,
        )
        try:
            raw_message_rows, raw_attachment_rows, raw_preview = self._raw_sensitive_values(
                self.db_path, chat_id
            )
            raw_dump = json.dumps(
                [raw_message_rows, raw_attachment_rows, raw_preview],
                ensure_ascii=False,
            )
            for secret in sentinels.values():
                self.assertNotIn(secret, raw_dump)

            with sqlite3.connect(self.db_path) as conn:
                self.assertEqual(
                    conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                    1,
                    "Chat payload migration must not hijack the generic schema version authority.",
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT migration_key FROM chat_payload_migrations WHERE migration_key = ?",
                        ("at_rest_v1",),
                    ).fetchone()[0],
                    "at_rest_v1",
                )

            restored = repo.get_session(chat_id)
            self.assertIsNotNone(restored)
            self.assertEqual(restored.last_message_preview, sentinels["preview"])
            self.assertEqual(restored.messages[0].content, sentinels["message"])
            self.assertEqual(
                restored.messages[0].agent_outputs.get("private_evidence"),
                sentinels["agent_output"],
            )
            self.assertEqual(restored.attachments[0].content, sentinels["attachment"])
        finally:
            repo.close()

    def test_migration_protection_failure_rolls_back_without_marker(self) -> None:
        sentinels = {
            "preview": "ROLLBACK_PREVIEW_SECRET_A1",
            "message": "ROLLBACK_MESSAGE_SECRET_B2",
            "agent_output": "ROLLBACK_AGENT_SECRET_C3",
            "attachment": "ROLLBACK_ATTACHMENT_SECRET_D4",
        }
        chat_id = self._create_legacy_v1_database(self.db_path, sentinels)

        with self.assertRaisesRegex(RuntimeError, "INJECTED_PAYLOAD_PROTECTION_FAILURE"):
            SQLiteChatRepository(
                db_path=self.db_path,
                payload_protector=_FailingPayloadProtector(fail_after=1),
            )

        raw_message_rows, raw_attachment_rows, raw_preview = self._raw_sensitive_values(
            self.db_path, chat_id
        )
        raw_dump = json.dumps(
            [raw_message_rows, raw_attachment_rows, raw_preview],
            ensure_ascii=False,
        )
        for secret in sentinels.values():
            self.assertIn(
                secret,
                raw_dump,
                "Failed migration must roll back every partial row update.",
            )

        with sqlite3.connect(self.db_path) as conn:
            marker = conn.execute(
                "SELECT migration_key FROM chat_payload_migrations WHERE migration_key = ?",
                ("at_rest_v1",),
            ).fetchone()
            self.assertIsNone(marker, "Failed migration must never record completion marker.")
            self.assertEqual(
                conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
