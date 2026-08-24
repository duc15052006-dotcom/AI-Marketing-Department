"""Chat Session Data Models & Management for AI Marketing Department.

Provides isolated multi-turn conversational chat sessions, message histories,
and temporary inline attachments backed by durable SQLite local storage.
Operates completely independently of brand onboarding.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("chat_session")


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM_STATUS = "system_status"
    SYSTEM = "system"
    AGENT = "agent"


class AttachmentType(str, Enum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"
    JSON = "json"
    CSV = "csv"
    IMAGE = "image"
    URL = "url"


@dataclass
class ChatAttachment:
    """Temporary attachment uploaded directly in a chat session."""

    chat_id: str
    filename_or_url: str
    attachment_type: AttachmentType
    content: str
    attachment_id: str = field(default_factory=lambda: f"ATT-{uuid.uuid4().hex[:8].upper()}")
    content_hash: str = ""
    source_type: str = "INLINE_UPLOAD"
    local_storage_ref: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    parser_status: str = "PARSED"
    content_size_bytes: int = 0

    def __post_init__(self) -> None:
        if not self.content_hash and self.content:
            self.content_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if not self.content_size_bytes and self.content:
            self.content_size_bytes = len(self.content.encode("utf-8"))

    def model_dump(self) -> Dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "chat_id": self.chat_id,
            "filename_or_url": self.filename_or_url,
            "attachment_type": self.attachment_type.value if hasattr(self.attachment_type, "value") else str(self.attachment_type),
            "content": self.content,
            "content_hash": self.content_hash,
            "source_type": self.source_type,
            "local_storage_ref": self.local_storage_ref,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "parser_status": self.parser_status,
            "content_size_bytes": self.content_size_bytes,
        }


@dataclass
class ChatMessage:
    """Individual conversational message within a chat thread."""

    chat_id: str
    role: ChatRole
    content: str
    sender_name: str = "User"
    message_id: str = field(default_factory=lambda: f"MSG-{uuid.uuid4().hex[:8].upper()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: Optional[str] = None
    status: str = "COMPLETED"
    sequence_number: int = 0
    agent_outputs: Optional[Dict[str, Any]] = None
    attachments: List[ChatAttachment] = field(default_factory=list)
    version: int = 1
    edit_history: List[Dict[str, Any]] = field(default_factory=list)

    def edit_content(self, new_content: str) -> None:
        """Preserve current content to edit history and update in-place safely."""
        self.edit_history.append({
            "version": self.version,
            "content": self.content,
            "edited_at": datetime.now(timezone.utc).isoformat(),
        })
        self.version += 1
        self.content = new_content

    def get_original_version(self) -> str:
        """Retrieve original unedited content."""
        if self.edit_history:
            return str(self.edit_history[0].get("content", self.content))
        return self.content

    def model_dump(self) -> Dict[str, Any]:
        return {
            "message_id": self.message_id,
            "chat_id": self.chat_id,
            "role": self.role.value if hasattr(self.role, "value") else str(self.role),
            "sender_name": self.sender_name,
            "content": self.content,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "run_id": self.run_id,
            "status": self.status,
            "sequence_number": self.sequence_number,
            "agent_outputs": self.agent_outputs,
            "attachments": [a.model_dump() for a in self.attachments],
            "version": self.version,
            "edit_history": self.edit_history,
        }


@dataclass
class ChatSession:
    """Isolated chat thread allowing zero-brand ad-hoc exploration or scoped execution."""

    title: str = "New Chat"
    chat_id: str = field(default_factory=lambda: f"CHAT-{uuid.uuid4().hex[:8].upper()}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "ACTIVE"
    optional_project_id: Optional[str] = None
    optional_business_id: Optional[str] = None
    archived: bool = False
    last_message_preview: str = ""
    last_run_id: Optional[str] = None
    messages: List[ChatMessage] = field(default_factory=list)
    attachments: List[ChatAttachment] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)

    def add_user_message(self, content: str, attachments: Optional[List[ChatAttachment]] = None) -> ChatMessage:
        seq = len(self.messages)
        msg = ChatMessage(
            chat_id=self.chat_id,
            role=ChatRole.USER,
            sender_name="User",
            content=content,
            sequence_number=seq,
            attachments=attachments or [],
        )
        self.messages.append(msg)
        if attachments:
            self.attachments.extend(attachments)
        self.updated_at = datetime.now(timezone.utc)
        self.last_message_preview = (content[:80] + "...") if len(content) > 80 else content
        return msg

    def add_assistant_response(
        self,
        content: str,
        run_id: Optional[str] = None,
        agent_outputs: Optional[Dict[str, Any]] = None,
        status: str = "COMPLETED",
    ) -> ChatMessage:
        seq = len(self.messages)
        msg = ChatMessage(
            chat_id=self.chat_id,
            role=ChatRole.ASSISTANT,
            sender_name="Five-Agent Department",
            content=content,
            run_id=run_id,
            status=status,
            sequence_number=seq,
            agent_outputs=agent_outputs,
        )
        self.messages.append(msg)
        if run_id:
            self.last_run_id = run_id
            if run_id not in self.run_ids:
                self.run_ids.append(run_id)
        self.updated_at = datetime.now(timezone.utc)
        self.last_message_preview = (content[:80] + "...") if len(content) > 80 else content
        return msg

    def add_system_status(self, content: str, run_id: Optional[str] = None) -> ChatMessage:
        seq = len(self.messages)
        msg = ChatMessage(
            chat_id=self.chat_id,
            role=ChatRole.SYSTEM_STATUS,
            sender_name="System",
            content=content,
            run_id=run_id,
            status="STATUS",
            sequence_number=seq,
        )
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def model_dump(self) -> Dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at),
            "status": self.status,
            "optional_project_id": self.optional_project_id,
            "optional_business_id": self.optional_business_id,
            "archived": self.archived,
            "last_message_preview": self.last_message_preview,
            "last_run_id": self.last_run_id,
            "messages": [m.model_dump() for m in self.messages],
            "attachments": [a.model_dump() for a in self.attachments],
            "run_ids": self.run_ids,
        }


class ChatSessionManager:
    """Manager for isolated chat sessions backed by SQLite repository."""

    def __init__(self, repository: Optional[Any] = None, db_path: Optional[Path | str] = None) -> None:
        if repository is not None:
            self.repo = repository
        else:
            from chat.repository import SQLiteChatRepository
            self.repo = SQLiteChatRepository(db_path=db_path)

        # In-memory dictionary mirror for rapid lookup and backward compatibility
        self._sessions: Dict[str, ChatSession] = {}
        self._reload_from_repo()

    def _reload_from_repo(self) -> None:
        """Hydrate in-memory state from durable SQLite database."""
        sessions = self.repo.list_sessions(include_archived=True)
        self._sessions = {s.chat_id: s for s in sessions}

    def create_session(
        self,
        title: str = "New Chat",
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> ChatSession:
        session = ChatSession(
            title=title,
            optional_project_id=project_id,
            optional_business_id=business_id,
        )
        self.repo.save_session(session)
        self._sessions[session.chat_id] = session
        return session

    def get_session(self, chat_id: str) -> Optional[ChatSession]:
        session = self.repo.get_session(chat_id)
        if session:
            self._sessions[chat_id] = session
        return session

    def list_sessions(
        self,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
        include_archived: bool = False,
    ) -> List[ChatSession]:
        sessions = self.repo.list_sessions(
            project_id=project_id,
            business_id=business_id,
            include_archived=include_archived,
        )
        for s in sessions:
            self._sessions[s.chat_id] = s
        return sessions

    def update_session(
        self,
        chat_id: str,
        title: Optional[str] = None,
        archived: Optional[bool] = None,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        business_id: Optional[str] = None,
    ) -> Optional[ChatSession]:
        updated = self.repo.update_session_metadata(
            chat_id=chat_id,
            title=title,
            archived=archived,
            status=status,
            project_id=project_id,
            business_id=business_id,
        )
        if updated:
            self._sessions[chat_id] = updated
        return updated

    def delete_session(self, chat_id: str) -> bool:
        ok = self.repo.delete_session(chat_id)
        if chat_id in self._sessions:
            del self._sessions[chat_id]
        return ok

    def add_user_message(
        self,
        chat_id: str,
        content: str,
        attachments: Optional[List[ChatAttachment]] = None,
    ) -> Optional[ChatMessage]:
        session = self.get_session(chat_id)
        if not session:
            return None
        msg = session.add_user_message(content, attachments=attachments)
        self.repo.save_message(msg)
        if attachments:
            for att in attachments:
                self.repo.save_attachment(att)
        self.repo.save_session(session)
        return msg

    def add_assistant_response(
        self,
        chat_id: str,
        content: str,
        run_id: Optional[str] = None,
        agent_outputs: Optional[Dict[str, Any]] = None,
        status: str = "COMPLETED",
    ) -> Optional[ChatMessage]:
        session = self.get_session(chat_id)
        if not session:
            return None
        msg = session.add_assistant_response(content, run_id=run_id, agent_outputs=agent_outputs, status=status)
        self.repo.save_message(msg)
        self.repo.save_session(session)
        return msg

    def add_attachment(self, attachment: ChatAttachment) -> ChatAttachment:
        self.repo.save_attachment(attachment)
        session = self.get_session(attachment.chat_id)
        if session:
            if not any(a.attachment_id == attachment.attachment_id for a in session.attachments):
                session.attachments.append(attachment)
                self.repo.save_session(session)
        return attachment

    def update_message(self, message_id: str, content: str, chat_id: Optional[str] = None) -> Optional[ChatMessage]:
        """Update an existing message safely with historical version preservation and persist to SQLite."""
        msg = self.repo.get_message(message_id)
        if not msg:
            return None
        if chat_id is not None and msg.chat_id != chat_id:
            logger.warning(f"Cross-chat message edit rejected: message {message_id} belongs to chat {msg.chat_id}, not {chat_id}")
            return None
        msg.edit_content(content)
        self.repo.save_message(msg)
        session = self.get_session(msg.chat_id)
        if session:
            for i, m in enumerate(session.messages):
                if m.message_id == message_id:
                    session.messages[i] = msg
                    break
            self.repo.save_session(session)
        return msg

    def get_message(self, message_id: str) -> Optional[ChatMessage]:
        """Retrieve a specific message by its message_id."""
        return self.repo.get_message(message_id)
