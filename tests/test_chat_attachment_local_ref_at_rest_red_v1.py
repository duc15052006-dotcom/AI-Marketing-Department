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


class ChatAttachmentLocalRefAtRestRedV1Tests(unittest.TestCase):
    def _persist(self, local_storage_ref: str):
        tmp = tempfile.TemporaryDirectory()
        db_path = Path(tmp.name) / "chat.sqlite3"
        protector = _TestOnlyProtector()
        repo = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
        session = ChatSession(title="attachment local ref test")
        repo.save_session(session)
        attachment = ChatAttachment(
            chat_id=session.chat_id,
            filename_or_url="upload.txt",
            attachment_type=AttachmentType.TEXT,
            content="protected parsed content",
            local_storage_ref=local_storage_ref,
        )
        repo.save_attachment(attachment)
        return tmp, db_path, protector, attachment

    def test_sensitive_local_storage_ref_is_not_plaintext_in_sqlite(self) -> None:
        secret = r"C:\Users\PrivateUser\AppData\Local\AI-Marketing\uploads\CLIENT_SECRET_52\plan.txt"
        tmp, db_path, _protector, attachment = self._persist(secret)
        try:
            with closing(sqlite3.connect(str(db_path))) as conn:
                raw = conn.execute(
                    "SELECT local_storage_ref FROM chat_attachments WHERE attachment_id = ?",
                    (attachment.attachment_id,),
                ).fetchone()[0]
            self.assertNotEqual(raw, secret, "local storage path reached raw SQLite as plaintext")
            self.assertNotIn("PrivateUser", str(raw))
            self.assertNotIn("CLIENT_SECRET_52", str(raw))
        finally:
            tmp.cleanup()

    def test_local_storage_ref_round_trips_after_restart(self) -> None:
        value = r"C:\Users\PrivateUser\Documents\campaign-plan.txt"
        tmp, db_path, protector, attachment = self._persist(value)
        try:
            restarted = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            loaded = restarted.get_attachment(attachment.attachment_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(value, loaded.local_storage_ref)
        finally:
            tmp.cleanup()

    def test_absent_local_storage_ref_remains_absent(self) -> None:
        tmp, db_path, protector, attachment = self._persist(None)
        try:
            restarted = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            loaded = restarted.get_attachment(attachment.attachment_id)
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertIsNone(loaded.local_storage_ref)
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
