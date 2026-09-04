from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from chat.repository import ChatPayloadProtector, SQLiteChatRepository
from chat.session import ChatSession


class _TestOnlyProtector(ChatPayloadProtector):
    """Deterministic reversible codec for storage-boundary tests only."""

    _PREFIX = "TESTPROTECTED:"

    def protect_text(self, value: str) -> str:
        return self._PREFIX + value[::-1]

    def unprotect_text(self, persisted_value: str) -> str:
        raw = str(persisted_value)
        if not raw.startswith(self._PREFIX):
            raise RuntimeError("expected test-protected payload")
        return raw[len(self._PREFIX):][::-1]


class ChatTitleAtRestAdversarialV1(unittest.TestCase):
    def test_session_title_and_rename_are_not_plaintext_at_rest_and_round_trip(self) -> None:
        initial_title = "CHAT_TITLE_SECRET_INITIAL_8C7D1A"
        renamed_title = "CHAT_TITLE_SECRET_RENAMED_4A19EF"

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "chat.sqlite3"
            protector = _TestOnlyProtector()
            repo = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)

            session = ChatSession(title=initial_title)
            repo.save_session(session)

            with sqlite3.connect(str(db_path)) as conn:
                raw_title = conn.execute(
                    "SELECT title FROM chat_sessions WHERE chat_id = ?",
                    (session.chat_id,),
                ).fetchone()[0]

            self.assertNotEqual(
                raw_title,
                initial_title,
                "Session title reached raw SQLite as plaintext.",
            )
            self.assertNotIn(initial_title, raw_title)

            fresh = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            loaded = fresh.get_session(session.chat_id, include_messages=False)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, initial_title)

            fresh.update_session_metadata(session.chat_id, title=renamed_title)
            with sqlite3.connect(str(db_path)) as conn:
                raw_renamed = conn.execute(
                    "SELECT title FROM chat_sessions WHERE chat_id = ?",
                    (session.chat_id,),
                ).fetchone()[0]

            self.assertNotEqual(
                raw_renamed,
                renamed_title,
                "Renamed session title reached raw SQLite as plaintext.",
            )
            self.assertNotIn(renamed_title, raw_renamed)

            restarted = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            loaded_after_rename = restarted.get_session(session.chat_id, include_messages=False)
            self.assertIsNotNone(loaded_after_rename)
            self.assertEqual(loaded_after_rename.title, renamed_title)

    def test_existing_at_rest_v1_database_migrates_plaintext_title(self) -> None:
        legacy_title = "CHAT_TITLE_LEGACY_SECRET_5D20CB"

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "chat.sqlite3"
            protector = _TestOnlyProtector()

            repo = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)
            session = ChatSession(title="temporary title")
            repo.save_session(session)

            # Force the exact persisted state produced by #153: at_rest_v1 is
            # complete, no title-specific migration marker exists, and title is
            # plaintext. This remains valid after the production fix lands.
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute(
                    "DELETE FROM chat_payload_migrations WHERE migration_key = ?",
                    ("title_at_rest_v1",),
                )
                conn.execute(
                    "UPDATE chat_sessions SET title = ? WHERE chat_id = ?",
                    (legacy_title, session.chat_id),
                )
                conn.commit()
                marker = conn.execute(
                    "SELECT 1 FROM chat_payload_migrations WHERE migration_key = ?",
                    ("at_rest_v1",),
                ).fetchone()
                raw_before = conn.execute(
                    "SELECT title FROM chat_sessions WHERE chat_id = ?",
                    (session.chat_id,),
                ).fetchone()[0]

            self.assertIsNotNone(marker)
            self.assertEqual(raw_before, legacy_title)

            reopened = SQLiteChatRepository(db_path=str(db_path), payload_protector=protector)

            with sqlite3.connect(str(db_path)) as conn:
                raw_after = conn.execute(
                    "SELECT title FROM chat_sessions WHERE chat_id = ?",
                    (session.chat_id,),
                ).fetchone()[0]
                title_marker = conn.execute(
                    "SELECT 1 FROM chat_payload_migrations WHERE migration_key = ?",
                    ("title_at_rest_v1",),
                ).fetchone()

            self.assertNotEqual(
                raw_after,
                legacy_title,
                "Existing #153 plaintext title was not migrated at repository startup.",
            )
            self.assertNotIn(legacy_title, raw_after)
            self.assertIsNotNone(title_marker)

            loaded = reopened.get_session(session.chat_id, include_messages=False)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.title, legacy_title)


if __name__ == "__main__":
    unittest.main()
