from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from chat.repository import ChatPayloadProtector, SQLiteChatRepository
from chat.session import AttachmentType, ChatAttachment, ChatSession


class _TestOnlyProtector(ChatPayloadProtector):
    _PREFIX = "TESTPROTECTED:"

    def protect_text(self, value: str) -> str:
        return self._PREFIX + value[::-1]

    def unprotect_text(self, persisted_value: str) -> str:
        raw = str(persisted_value)
        if not raw.startswith(self._PREFIX):
            raise RuntimeError("expected protected payload")
        return raw[len(self._PREFIX):][::-1]


class ChatAttachmentFilenameAtRestRedV1Tests(unittest.TestCase):
    def _persist(self, filename_or_url: str):
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "chat.sqlite3"
        protector = _TestOnlyProtector()
        repo = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
        session = ChatSession(title="attachment metadata test")
        repo.save_session(session)
        attachment = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url=filename_or_url,
            attachment_type=AttachmentType.TEXT,
            content="protected parsed content",
        )
        repo.save_attachment(attachment)
        return tmp, db_path, protector, attachment

    def test_sensitive_attachment_filename_is_not_plaintext_in_sqlite(self) -> None:
        secret = "Acquisition_Targets_SECRET_7F4C19.xlsx"
        tmp, db_path, _protector, attachment = self._persist(secret)
        try:
            with closing(sqlite3.connect(str(db_path))) as conn:
                raw = conn.execute(
                    "SELECT filename FROM chat_attachments WHERE attachment_id = ?",
                    (attachment.attachment_id,),
                ).fetchone()[0]
            self.assertNotEqual(raw, secret, "sensitive attachment filename reached raw SQLite as plaintext")
            self.assertNotIn(secret, str(raw))
        finally:
            tmp.cleanup()

    def test_sensitive_attachment_url_is_not_plaintext_in_sqlite(self) -> None:
        secret = "https://private.example/report?customer=ACME-SECRET-91&token=URLSECRET"
        tmp, db_path, _protector, attachment = self._persist(secret)
        try:
            with closing(sqlite3.connect(str(db_path))) as conn:
                raw = conn.execute(
                    "SELECT filename FROM chat_attachments WHERE attachment_id = ?",
                    (attachment.attachment_id,),
                ).fetchone()[0]
            self.assertNotEqual(raw, secret, "sensitive attachment URL reached raw SQLite as plaintext")
            self.assertNotIn("URLSECRET", str(raw))
        finally:
            tmp.cleanup()

    def test_attachment_filename_round_trips_after_restart(self) -> None:
        value = "quarterly-plan-private.txt"
        tmp, db_path, protector, attachment = self._persist(value)
        try:
            restarted = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            loaded = restarted.get_attachment(attachment.attachment_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(value, loaded.filename_or_url)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
