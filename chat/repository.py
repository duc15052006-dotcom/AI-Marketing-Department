"""SQLite Persistence and Repository Layer for Chat Sessions, Messages, and Attachments.

Provides durable, ACID-compliant local SQLite storage for:
- ChatSession (creation, update, rename, archive, delete)
- ChatMessage (user, assistant, system_status with sequence ordering)
- ChatAttachment (inline attachments isolated strictly per chat_id)

Ensures zero cross-chat knowledge leakage and survivability across app restarts.
"""

from __future__ import annotations

import abc
import base64
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional

from chat.session import AttachmentType, ChatAttachment, ChatMessage, ChatRole, ChatSession

logger = logging.getLogger("chat_repository")


class ChatPayloadProtectionError(RuntimeError):
    """Raised when persisted chat payload cannot be safely protected/recovered."""


class ChatPayloadProtector(abc.ABC):
    """Narrow storage codec contract for sensitive chat payload text."""

    @abc.abstractmethod
    def protect_text(self, value: str) -> str:
        raise NotImplementedError

    @abc.abstractmethod
    def unprotect_text(self, persisted_value: str) -> str:
        raise NotImplementedError


class _DPAPIChatPayloadProtector(ChatPayloadProtector):
    """Windows user-bound DPAPI envelope for chat payloads.

    Uses the existing OS-backed DPAPI primitive from the credential security
    module, but does not create or resolve credential refs. The constant entropy
    provides purpose separation only; it is not a secret.
    """

    _PREFIX = "DPAPI1:"
    _ENTROPY = b"AI-Marketing-Dept-Chat-Payload-v1"

    def protect_text(self, value: str) -> str:
        from integrations.models.secret_store import _win_dpapi_encrypt

        try:
            encrypted = _win_dpapi_encrypt(str(value).encode("utf-8"), self._ENTROPY)
        except Exception as exc:
            raise ChatPayloadProtectionError(
                "CHAT_PAYLOAD_PROTECTION_UNAVAILABLE: refusing plaintext persistence"
            ) from exc
        return self._PREFIX + base64.b64encode(encrypted).decode("ascii")

    def unprotect_text(self, persisted_value: str) -> str:
        from integrations.models.secret_store import _win_dpapi_decrypt

        raw = str(persisted_value)
        if not raw.startswith(self._PREFIX):
            raise ChatPayloadProtectionError(
                "CHAT_PAYLOAD_UNPROTECTED_OR_CORRUPT: expected protected envelope"
            )
        try:
            encrypted = base64.b64decode(raw[len(self._PREFIX):], validate=True)
            plaintext = _win_dpapi_decrypt(encrypted, self._ENTROPY)
            return plaintext.decode("utf-8")
        except ChatPayloadProtectionError:
            raise
        except Exception as exc:
            raise ChatPayloadProtectionError(
                "CHAT_PAYLOAD_DECRYPT_FAILED: refusing unsafe fallback"
            ) from exc


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app_v1.sqlite"


class ChatRepository(abc.ABC):
    @abc.abstractmethod
    def save_session(self, session: ChatSession) -> ChatSession:
        pass

    @abc.abstractmethod
    def get_session(self, chat_id: str, include_messages: bool = True) -> Optional[ChatSession]:
        pass

    @abc.abstractmethod
    def list_sessions(
        self,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[ChatSession]:
        pass

    @abc.abstractmethod
    def update_session_metadata(
        self,
        chat_id: str,
        title: Optional[str] = None,
        archived: Optional[bool] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> Optional[ChatSession]:
        pass

    @abc.abstractmethod
    def delete_session(self, chat_id: str) -> bool:
        pass


class MessageRepository(abc.ABC):
    @abc.abstractmethod
    def save_message(self, message: ChatMessage) -> ChatMessage:
        pass

    @abc.abstractmethod
    def list_messages(self, chat_id: str) -> List[ChatMessage]:
        pass

    @abc.abstractmethod
    def get_message(self, message_id: str) -> Optional[ChatMessage]:
        pass


class ChatAttachmentRepository(abc.ABC):
    @abc.abstractmethod
    def save_attachment(self, attachment: ChatAttachment) -> ChatAttachment:
        pass

    @abc.abstractmethod
    def list_attachments(self, chat_id: str) -> List[ChatAttachment]:
        """List all attachments for a chat."""
        raise NotImplementedError

    def close(self) -> None:
        """Release any held repository resources."""
        pass


class SQLiteChatRepository(ChatRepository, MessageRepository, ChatAttachmentRepository):
    """Production SQLite storage implementation with migration versioning and WAL mode."""

    CURRENT_SCHEMA_VERSION = 1

    def __init__(
        self,
        db_path: Optional[str] = None,
        payload_protector: Optional[ChatPayloadProtector] = None,
    ) -> None:
        if db_path is None:
            from config.authority import get_runtime_config
            configured_path = get_runtime_config().department_db_path
            db_path = configured_path if configured_path else str(DEFAULT_DB_PATH)
        self.db_path = Path(db_path)
        self._payload_protector = payload_protector or _DPAPIChatPayloadProtector()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def close(self) -> None:
        """Release repository resources."""
        pass

    def _protect_text(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return self._payload_protector.protect_text(str(value))

    def _unprotect_text(self, persisted_value: Optional[str]) -> Optional[str]:
        if persisted_value is None:
            return None
        return self._payload_protector.unprotect_text(str(persisted_value))

    def _migrate_v1_plaintext_payloads(self, conn: sqlite3.Connection) -> None:
        """Atomically convert legacy sensitive TEXT payloads to protected envelopes."""
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_payload_migrations (
                migration_key TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            """
        )
        marker = conn.execute(
            "SELECT 1 FROM chat_payload_migrations WHERE migration_key = ?",
            ("at_rest_v1",),
        ).fetchone()
        if marker:
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in conn.execute(
                "SELECT chat_id, last_message_preview FROM chat_sessions"
            ).fetchall():
                conn.execute(
                    "UPDATE chat_sessions SET last_message_preview = ? WHERE chat_id = ?",
                    (self._protect_text(row["last_message_preview"] or ""), row["chat_id"]),
                )

            for row in conn.execute(
                "SELECT message_id, content, agent_outputs_json FROM chat_messages"
            ).fetchall():
                conn.execute(
                    "UPDATE chat_messages SET content = ?, agent_outputs_json = ? WHERE message_id = ?",
                    (
                        self._protect_text(row["content"]),
                        self._protect_text(row["agent_outputs_json"]) if row["agent_outputs_json"] is not None else None,
                        row["message_id"],
                    ),
                )

            for row in conn.execute(
                "SELECT attachment_id, content FROM chat_attachments"
            ).fetchall():
                conn.execute(
                    "UPDATE chat_attachments SET content = ? WHERE attachment_id = ?",
                    (self._protect_text(row["content"]), row["attachment_id"]),
                )

            conn.execute(
                "INSERT INTO chat_payload_migrations (migration_key, applied_at) VALUES (?, ?)",
                ("at_rest_v1", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _migrate_plaintext_session_titles(self, conn: sqlite3.Connection) -> None:
        """Atomically protect session titles left plaintext by at_rest_v1."""
        marker = conn.execute(
            "SELECT 1 FROM chat_payload_migrations WHERE migration_key = ?",
            ("title_at_rest_v1",),
        ).fetchone()
        if marker:
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in conn.execute(
                "SELECT chat_id, title FROM chat_sessions"
            ).fetchall():
                conn.execute(
                    "UPDATE chat_sessions SET title = ? WHERE chat_id = ?",
                    (self._protect_text(row["title"]), row["chat_id"]),
                )

            conn.execute(
                "INSERT INTO chat_payload_migrations (migration_key, applied_at) VALUES (?, ?)",
                ("title_at_rest_v1", datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA busy_timeout = 30000;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create tables and run migrations safely."""
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """
            )

            cur = conn.execute("SELECT MAX(version) FROM schema_migrations")
            row = cur.fetchone()
            current_ver = row[0] if row and row[0] is not None else 0

            if current_ver < 1:
                # Schema version 1
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS chat_sessions (
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

                    CREATE TABLE IF NOT EXISTS chat_messages (
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

                    CREATE TABLE IF NOT EXISTS chat_attachments (
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

                    CREATE INDEX IF NOT EXISTS idx_chat_messages_chat_id ON chat_messages(chat_id);
                    CREATE INDEX IF NOT EXISTS idx_chat_attachments_chat_id ON chat_attachments(chat_id);
                    CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at DESC);
                    """
                )
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (1, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()

            self._migrate_v1_plaintext_payloads(conn)
            self._migrate_plaintext_session_titles(conn)

    # =========================================================================
    # ChatSession Methods
    # =========================================================================
    def save_session(self, session: ChatSession) -> ChatSession:
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO chat_sessions (
                    chat_id, title, created_at, updated_at, status,
                    project_id, business_id, archived, last_message_preview, last_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    title = excluded.title,
                    updated_at = excluded.updated_at,
                    status = excluded.status,
                    project_id = excluded.project_id,
                    business_id = excluded.business_id,
                    archived = excluded.archived,
                    last_message_preview = excluded.last_message_preview,
                    last_run_id = excluded.last_run_id;
                """,
                (
                    session.chat_id,
                    self._protect_text(session.title),
                    session.created_at.isoformat() if isinstance(session.created_at, datetime) else str(session.created_at),
                    session.updated_at.isoformat() if isinstance(session.updated_at, datetime) else str(session.updated_at),
                    session.status,
                    session.optional_project_id,
                    session.optional_business_id,
                    1 if session.archived else 0,
                    self._protect_text(session.last_message_preview),
                    session.last_run_id,
                ),
            )

            # Persist any messages that might not yet be in DB
            for idx, msg in enumerate(session.messages):
                msg.sequence_number = idx
                self._save_message_with_conn(conn, msg)

            # Persist attachments
            for att in session.attachments:
                self._save_attachment_with_conn(conn, att)

            conn.commit()
        return session

    def get_session(self, chat_id: str, include_messages: bool = True) -> Optional[ChatSession]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM chat_sessions WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            if not row:
                return None

            session = self._row_to_session(row)
            if include_messages:
                session.messages = self._list_messages_with_conn(conn, chat_id)
                session.attachments = self._list_attachments_with_conn(conn, chat_id)
                session.run_ids = list(
                    set([m.run_id for m in session.messages if m.run_id] + ([session.last_run_id] if session.last_run_id else []))
                )
            return session

    def list_sessions(
        self,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[ChatSession]:
        query = "SELECT * FROM chat_sessions WHERE 1=1"
        params: List[Any] = []

        if not include_archived:
            query += " AND archived = 0"
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        if business_id:
            query += " AND business_id = ?"
            params.append(business_id)

        query += " ORDER BY updated_at DESC"

        with self._get_connection() as conn:
            cur = conn.execute(query, tuple(params))
            rows = cur.fetchall()
            sessions = []
            for row in rows:
                s = self._row_to_session(row)
                s.messages = self._list_messages_with_conn(conn, s.chat_id)
                s.attachments = self._list_attachments_with_conn(conn, s.chat_id)
                sessions.append(s)
            return sessions

    def update_session_metadata(
        self,
        chat_id: str,
        title: Optional[str] = None,
        archived: Optional[bool] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> Optional[ChatSession]:
        updates = []
        params = []
        now_str = datetime.now(timezone.utc).isoformat()

        if title is not None:
            updates.append("title = ?")
            params.append(self._protect_text(title))
        if archived is not None:
            updates.append("archived = ?")
            params.append(1 if archived else 0)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if project_id is not None:
            updates.append("project_id = ?")
            params.append(project_id)
        if business_id is not None:
            updates.append("business_id = ?")
            params.append(business_id)

        if not updates:
            return self.get_session(chat_id)

        updates.append("updated_at = ?")
        params.append(now_str)
        params.append(chat_id)

        with self._get_connection() as conn:
            conn.execute(f"UPDATE chat_sessions SET {', '.join(updates)} WHERE chat_id = ?", tuple(params))
            conn.commit()

        return self.get_session(chat_id)

    def delete_session(self, chat_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))
            conn.commit()
            return cur.rowcount > 0

    # =========================================================================
    # ChatMessage Methods
    # =========================================================================
    def save_message(self, message: ChatMessage) -> ChatMessage:
        with self._get_connection() as conn:
            self._save_message_with_conn(conn, message)
            preview = (message.content[:80] + "...") if len(message.content) > 80 else message.content
            conn.execute(
                """
                UPDATE chat_sessions SET
                    updated_at = ?,
                    last_message_preview = ?,
                    last_run_id = COALESCE(?, last_run_id)
                WHERE chat_id = ?;
                """,
                (
                    message.created_at.isoformat() if isinstance(message.created_at, datetime) else str(message.created_at),
                    self._protect_text(preview),
                    message.run_id,
                    message.chat_id,
                ),
            )
            conn.commit()
        return message

    def _save_message_with_conn(self, conn: sqlite3.Connection, message: ChatMessage) -> None:
        meta_dict = dict(message.agent_outputs or {})
        if getattr(message, "version", 1) > 1 or getattr(message, "edit_history", []):
            meta_dict["_version"] = getattr(message, "version", 1)
            meta_dict["_edit_history"] = getattr(message, "edit_history", [])
        agent_out_str = json.dumps(meta_dict) if meta_dict else None
        role_str = message.role.value if hasattr(message.role, "value") else str(message.role)

        conn.execute(
            """
            INSERT INTO chat_messages (
                message_id, chat_id, role, sender_name, content,
                created_at, run_id, status, sequence_number, agent_outputs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                content = excluded.content,
                run_id = excluded.run_id,
                status = excluded.status,
                agent_outputs_json = excluded.agent_outputs_json;
            """,
            (
                message.message_id,
                message.chat_id,
                role_str,
                message.sender_name,
                self._protect_text(message.content),
                message.created_at.isoformat() if isinstance(message.created_at, datetime) else str(message.created_at),
                message.run_id,
                message.status,
                message.sequence_number,
                self._protect_text(agent_out_str) if agent_out_str is not None else None,
            ),
        )

        # Save any attachments attached directly to this message
        for att in getattr(message, "attachments", []):
            if not att.chat_id:
                att.chat_id = message.chat_id
            self._save_attachment_with_conn(conn, att)

    def list_messages(self, chat_id: str) -> List[ChatMessage]:
        with self._get_connection() as conn:
            return self._list_messages_with_conn(conn, chat_id)

    def _list_messages_with_conn(self, conn: sqlite3.Connection, chat_id: str) -> List[ChatMessage]:
        cur = conn.execute(
            "SELECT * FROM chat_messages WHERE chat_id = ? ORDER BY sequence_number ASC, created_at ASC",
            (chat_id,),
        )
        rows = cur.fetchall()
        messages = [self._row_to_message(r) for r in rows]
        attachments = self._list_attachments_with_conn(conn, chat_id)
        if attachments and messages:
            # Associate attachments to messages in this chat
            for msg in messages:
                if msg.role == ChatRole.USER:
                    msg.attachments = [a for a in attachments if a.chat_id == chat_id]
        return messages

    def get_message(self, message_id: str) -> Optional[ChatMessage]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM chat_messages WHERE message_id = ?", (message_id,))
            row = cur.fetchone()
            if not row:
                return None
            msg = self._row_to_message(row)
            attachments = self._list_attachments_with_conn(conn, msg.chat_id)
            if attachments and msg.role == ChatRole.USER:
                msg.attachments = attachments
            return msg

    # =========================================================================
    # ChatAttachment Methods
    # =========================================================================
    def save_attachment(self, attachment: ChatAttachment) -> ChatAttachment:
        with self._get_connection() as conn:
            self._save_attachment_with_conn(conn, attachment)
            conn.commit()
        return attachment

    def _save_attachment_with_conn(self, conn: sqlite3.Connection, attachment: ChatAttachment) -> None:
        type_str = attachment.attachment_type.value if hasattr(attachment.attachment_type, "value") else str(attachment.attachment_type)
        conn.execute(
            """
            INSERT INTO chat_attachments (
                attachment_id, chat_id, filename, media_type, content,
                content_hash, source_type, local_storage_ref, created_at,
                parser_status, content_size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(attachment_id) DO UPDATE SET
                content = excluded.content,
                content_hash = excluded.content_hash,
                parser_status = excluded.parser_status,
                content_size_bytes = excluded.content_size_bytes;
            """,
            (
                attachment.attachment_id,
                attachment.chat_id,
                attachment.filename_or_url,
                type_str,
                self._protect_text(attachment.content),
                attachment.content_hash,
                getattr(attachment, "source_type", "INLINE_UPLOAD"),
                getattr(attachment, "local_storage_ref", None),
                attachment.created_at.isoformat() if isinstance(attachment.created_at, datetime) else str(attachment.created_at),
                getattr(attachment, "parser_status", "PARSED"),
                attachment.content_size_bytes,
            ),
        )

    def list_attachments(self, chat_id: str) -> List[ChatAttachment]:
        with self._get_connection() as conn:
            return self._list_attachments_with_conn(conn, chat_id)

    def _list_attachments_with_conn(self, conn: sqlite3.Connection, chat_id: str) -> List[ChatAttachment]:
        cur = conn.execute(
            "SELECT * FROM chat_attachments WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,),
        )
        rows = cur.fetchall()
        return [self._row_to_attachment(r) for r in rows]

    def get_attachment(self, attachment_id: str) -> Optional[ChatAttachment]:
        with self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM chat_attachments WHERE attachment_id = ?", (attachment_id,))
            row = cur.fetchone()
            return self._row_to_attachment(row) if row else None

    # =========================================================================
    # Row Deserializers
    # =========================================================================
    def _row_to_session(self, row: sqlite3.Row) -> ChatSession:
        created_dt = self._parse_iso(row["created_at"])
        updated_dt = self._parse_iso(row["updated_at"])

        return ChatSession(
            chat_id=row["chat_id"],
            title=self._unprotect_text(row["title"]) or "",
            created_at=created_dt,
            updated_at=updated_dt,
            status=row["status"],
            optional_project_id=row["project_id"],
            optional_business_id=row["business_id"],
            archived=bool(row["archived"]),
            last_message_preview=self._unprotect_text(row["last_message_preview"]) or "",
            last_run_id=row["last_run_id"],
            messages=[],
            attachments=[],
            run_ids=[],
        )

    def _row_to_message(self, row: sqlite3.Row) -> ChatMessage:
        role_str = row["role"].lower()
        role_enum = ChatRole.USER
        if role_str == "assistant":
            role_enum = ChatRole.ASSISTANT
        elif role_str == "system_status" or role_str == "system":
            role_enum = ChatRole.SYSTEM_STATUS
        elif role_str == "agent":
            role_enum = ChatRole.AGENT

        agent_payload = self._unprotect_text(row["agent_outputs_json"]) if row["agent_outputs_json"] is not None else None
        agent_raw = json.loads(agent_payload) if agent_payload else {}
        agent_out = dict(agent_raw) if isinstance(agent_raw, dict) else {}
        version = agent_out.pop("_version", 1) if isinstance(agent_out, dict) else 1
        edit_history = agent_out.pop("_edit_history", []) if isinstance(agent_out, dict) else []
        created_dt = self._parse_iso(row["created_at"])

        return ChatMessage(
            message_id=row["message_id"],
            chat_id=row["chat_id"],
            role=role_enum,
            sender_name=row["sender_name"],
            content=self._unprotect_text(row["content"]) or "",
            created_at=created_dt,
            run_id=row["run_id"],
            status=row["status"],
            sequence_number=row["sequence_number"],
            agent_outputs=agent_out if agent_out else None,
            attachments=[],
            version=version,
            edit_history=edit_history,
        )

    def _row_to_attachment(self, row: sqlite3.Row) -> ChatAttachment:
        type_str = row["media_type"].lower()
        type_enum = AttachmentType.TEXT
        for member in AttachmentType:
            if member.value == type_str or member.name.lower() == type_str:
                type_enum = member
                break

        created_dt = self._parse_iso(row["created_at"])

        att = ChatAttachment(
            attachment_id=row["attachment_id"],
            chat_id=row["chat_id"],
            filename_or_url=row["filename"],
            attachment_type=type_enum,
            content=self._unprotect_text(row["content"]) or "",
            content_hash=row["content_hash"],
            created_at=created_dt,
            source_type=row["source_type"],
            local_storage_ref=row["local_storage_ref"],
            parser_status=row["parser_status"],
            content_size_bytes=row["content_size_bytes"],
        )
        return att

    @staticmethod
    def _parse_iso(val: Any) -> datetime:
        if isinstance(val, datetime):
            return val
        if not val:
            return datetime.now(timezone.utc)
        try:
            return datetime.fromisoformat(str(val))
        except Exception:
            return datetime.now(timezone.utc)
