"""Ephemeral Session Knowledge Store for AI Marketing Department.

Provides temporary, in-memory knowledge indexing for inline chat attachments.
Guarantees that session data is never automatically written into persistent global
or brand knowledge repositories.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chat.session import AttachmentType, ChatAttachment


@dataclass
class SessionChunk:
    """Ephemeral chunk from a session attachment."""

    chunk_id: str
    attachment_id: str
    chat_id: str
    chunk_index: int
    text: str
    token_count_approx: int = 0

    def __post_init__(self) -> None:
        if not self.token_count_approx and self.text:
            self.token_count_approx = len(self.text.split())

    def model_dump(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "attachment_id": self.attachment_id,
            "chat_id": self.chat_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "token_count_approx": self.token_count_approx,
        }


@dataclass
class SessionDocument:
    """Ephemeral document created from an inline chat attachment."""

    attachment_id: str
    chat_id: str
    filename_or_url: str
    attachment_type: AttachmentType
    raw_content: str
    content_hash: str
    chunks: List[SessionChunk] = field(default_factory=list)

    def model_dump(self) -> Dict[str, Any]:
        return {
            "attachment_id": self.attachment_id,
            "chat_id": self.chat_id,
            "filename_or_url": self.filename_or_url,
            "attachment_type": self.attachment_type.value if hasattr(self.attachment_type, "value") else str(self.attachment_type),
            "raw_content": self.raw_content,
            "content_hash": self.content_hash,
            "chunks": [c.model_dump() for c in self.chunks],
        }


class SessionKnowledgeStore:
    """Manages ephemeral in-memory knowledge per chat session with zero auto-persistence."""

    def __init__(self) -> None:
        # chat_id -> Dict[attachment_id, SessionDocument]
        self._session_docs: Dict[str, Dict[str, SessionDocument]] = {}

    def index_attachment(self, attachment: ChatAttachment) -> SessionDocument:
        """Parse and chunk an attachment into ephemeral memory."""
        if attachment.chat_id not in self._session_docs:
            self._session_docs[attachment.chat_id] = {}

        raw_text = attachment.content
        blocks = [b.strip() for b in re.split(r"\n\s*\n", raw_text) if b.strip()]
        if not blocks:
            blocks = [raw_text.strip()] if raw_text.strip() else ["(empty content)"]

        chunks: List[SessionChunk] = []
        for idx, block in enumerate(blocks):
            cid = f"SCHUNK-{attachment.attachment_id}-{idx}"
            chunks.append(
                SessionChunk(
                    chunk_id=cid,
                    attachment_id=attachment.attachment_id,
                    chat_id=attachment.chat_id,
                    chunk_index=idx,
                    text=block,
                )
            )

        doc = SessionDocument(
            attachment_id=attachment.attachment_id,
            chat_id=attachment.chat_id,
            filename_or_url=attachment.filename_or_url,
            attachment_type=attachment.attachment_type,
            raw_content=attachment.content,
            content_hash=attachment.content_hash,
            chunks=chunks,
        )
        self._session_docs[attachment.chat_id][attachment.attachment_id] = doc
        return doc

    def get_session_documents(self, chat_id: str) -> List[SessionDocument]:
        return list(self._session_docs.get(chat_id, {}).values())

    def search_session(self, chat_id: str, query: str, top_k: int = 5) -> List[SessionChunk]:
        """Search across chunks belonging exclusively to the specified chat session."""
        docs = self.get_session_documents(chat_id)
        if not docs:
            return []

        query_terms = set(re.findall(r"\w+", query.lower()))
        scored_chunks: List[tuple[int, SessionChunk]] = []

        for doc in docs:
            doc_terms = set(re.findall(r"\w+", (doc.filename_or_url or "").lower()))
            for ch in doc.chunks:
                chunk_terms = set(re.findall(r"\w+", ch.text.lower())).union(doc_terms)
                overlap = len(query_terms.intersection(chunk_terms))
                if overlap > 0 or not query_terms:
                    scored_chunks.append((overlap, ch))

        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored_chunks[:top_k]]

    def clear_session(self, chat_id: str) -> None:
        """Discard all ephemeral documents for the chat session."""
        if chat_id in self._session_docs:
            del self._session_docs[chat_id]
