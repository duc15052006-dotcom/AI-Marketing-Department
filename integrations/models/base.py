"""Provider-Independent Model Adapter Base Interfaces.

Decouples agent reasoning from specific LLM providers.
Normalizes requests, responses, token tracking, latency, and provider provenance metadata.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generator, List, Optional
from schemas.base import BaseModel, Field


class ModelRole(str, Enum):
    """Standard message roles across all LLM providers."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    MODEL = "model"


class ModelMessage(BaseModel):
    """Standard message representation across LLM providers."""
    role: ModelRole = Field(default=ModelRole.USER, description="system, user, assistant, model, or tool")
    content: str = ""
    name: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.role, str) and not isinstance(self.role, ModelRole):
            r_str = self.role.lower()
            if r_str in [e.value for e in ModelRole]:
                self.role = ModelRole(r_str)


def normalize_model_message(msg: Any) -> ModelMessage:
    """Normalize a message from ModelMessage, dict, or legacy mapping into a canonical ModelMessage.

    Fails closed with ValueError for malformed or missing required role/content fields.
    """
    if msg is None:
        raise ValueError("REQUEST_SCHEMA_ERROR: Message cannot be None.")

    if isinstance(msg, ModelMessage):
        if not hasattr(msg, "role") or msg.role is None:
            raise ValueError("REQUEST_SCHEMA_ERROR: ModelMessage is missing required 'role'.")
        if not hasattr(msg, "content") or msg.content is None or not isinstance(msg.content, str):
            raise ValueError("REQUEST_SCHEMA_ERROR: ModelMessage is missing or has non-string 'content'.")

        role_val = msg.role
        if isinstance(role_val, str) and not isinstance(role_val, ModelRole):
            r_str = role_val.lower()
            if r_str in [e.value for e in ModelRole]:
                role_val = ModelRole(r_str)
            else:
                raise ValueError(f"REQUEST_SCHEMA_ERROR: Invalid message role '{role_val}'.")
        return ModelMessage(role=role_val, content=msg.content, name=getattr(msg, "name", None))

    if isinstance(msg, dict):
        if "role" not in msg or msg["role"] is None:
            raise ValueError("REQUEST_SCHEMA_ERROR: Message dict is missing required 'role' key.")
        if "content" not in msg or msg["content"] is None:
            raise ValueError("REQUEST_SCHEMA_ERROR: Message dict is missing required 'content' key.")
        if not isinstance(msg["content"], str):
            raise ValueError(f"REQUEST_SCHEMA_ERROR: Message content must be a string, got {type(msg['content']).__name__}.")

        raw_role = msg["role"]
        if isinstance(raw_role, ModelRole):
            role_enum = raw_role
        elif isinstance(raw_role, str):
            r_str = raw_role.lower()
            if r_str in [e.value for e in ModelRole]:
                role_enum = ModelRole(r_str)
            else:
                raise ValueError(f"REQUEST_SCHEMA_ERROR: Invalid message role string '{raw_role}'.")
        else:
            raise ValueError(f"REQUEST_SCHEMA_ERROR: Message role must be a string or ModelRole, got {type(raw_role).__name__}.")

        return ModelMessage(role=role_enum, content=msg["content"], name=msg.get("name"))

    raise ValueError(f"REQUEST_SCHEMA_ERROR: Invalid message type '{type(msg).__name__}'. Expected ModelMessage or dict.")


def normalize_model_request(req: Any) -> ModelRequest:
    """Normalize a ModelRequest ensuring all messages are canonical ModelMessage instances.

    Fails closed with ValueError for malformed requests.
    """
    if req is None:
        raise ValueError("REQUEST_SCHEMA_ERROR: Request cannot be None.")
    if not isinstance(req, ModelRequest):
        raise ValueError(f"REQUEST_SCHEMA_ERROR: Expected ModelRequest instance, got {type(req).__name__}.")

    if not isinstance(req.messages, list) or len(req.messages) == 0:
        raise ValueError("REQUEST_SCHEMA_ERROR: ModelRequest.messages must be a non-empty list.")

    canonical_messages = [normalize_model_message(m) for m in req.messages]

    return ModelRequest(
        request_id=req.request_id,
        model_name=req.model_name,
        messages=canonical_messages,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        response_schema=req.response_schema,
        tools=req.tools,
        timeout_seconds=req.timeout_seconds,
        metadata=dict(req.metadata) if req.metadata else {},
    )


class ModelUsage(BaseModel):
    """Normalized token usage metadata directly reported by provider."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thoughts_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    tool_use_prompt_tokens: Optional[int] = None
    total_tokens: int = 0
    usage_source: str = "NOT_AVAILABLE"


class ModelRequest(BaseModel):
    """Standard unified LLM invocation request."""
    request_id: str = Field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:12]}")
    model_name: str = Field(default="default")
    messages: List[ModelMessage] = Field(default_factory=list)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=4096)
    response_schema: Optional[Dict[str, Any]] = None  # JSON schema for structured output
    tools: Optional[List[Dict[str, Any]]] = None
    timeout_seconds: float = Field(default=60.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if isinstance(self.messages, list):
            self.messages = [
                normalize_model_message(m) if not (isinstance(m, ModelMessage) and isinstance(m.role, ModelRole)) else m
                for m in self.messages
            ]


class ModelResponseStatus(str, Enum):
    """Normalized status of a model completion."""
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    STREAM_UNSUPPORTED = "STREAM_UNSUPPORTED"


MAX_SAFE_MESSAGE_LEN: int = 500


class ModelStreamError(BaseModel):
    """Structured, provider-independent stream error diagnostic.

    Never contains API keys, bearer tokens, passwords, raw headers,
    or unsanitized provider response bodies.
    """
    code: str = Field(description="Standardized error code (e.g. AUTH_ERROR, RATE_LIMITED, TIMEOUT, etc.)")
    category: str = Field(description="High-level error category (e.g. AUTHENTICATION, RATE_LIMIT, TIMEOUT, NETWORK, SERVER_ERROR, etc.)")
    safe_message: str = Field(description="Sanitized, user-safe error message containing no secrets or keys")
    retryable: bool = Field(default=False, description="Whether the operation can be retried")
    http_status: Optional[int] = Field(default=None, description="HTTP status code if applicable")

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.code:
            self.code = "STREAM_INTERNAL_ERROR"
        if not self.category:
            self.category = "INTERNAL"
        if self.safe_message and len(self.safe_message) > MAX_SAFE_MESSAGE_LEN:
            self.safe_message = self.safe_message[:MAX_SAFE_MESSAGE_LEN - 3] + "..."


class StreamDelta(BaseModel):
    """Visible-only content delta from a streaming model response.

    Contains only user-visible assistant text. Internal reasoning,
    chain-of-thought, analysis, and provider-specific hidden fields
    are never included.
    """
    content: str = ""
    finish_reason: Optional[str] = None
    provider: str = ""
    model_name: str = ""
    error: Optional[ModelStreamError] = None


class ModelResponse(BaseModel):
    """Standard unified LLM invocation response with provenance and trust metadata."""
    request_id: str
    provider: str
    model_name: str
    status: ModelResponseStatus = ModelResponseStatus.SUCCESS
    content: str = ""
    structured_output: Optional[Dict[str, Any]] = None
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Provenance, Trust and Routing metadata
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary routing, resolution, and provider metadata")
    provider_type: str = Field(default="first_party", description="first_party | third_party_openai_compatible")
    provider_provenance: str = Field(default="FIRST_PARTY", description="FIRST_PARTY | THIRD_PARTY")
    model_provenance: str = Field(
        default="VERIFIED_FIRST_PARTY",
        description="VERIFIED_FIRST_PARTY | UNVERIFIED_THIRD_PARTY_CLAIM | SELF_REPORTED_BY_PROVIDER",
    )
    trust_status: str = Field(default="VERIFIED", description="VERIFIED | UNVERIFIED")


class CostPolicy(str, Enum):
    """Cost governance classification for model providers."""
    FREE_TIER_ALLOWED = "FREE_TIER_ALLOWED"
    PAID = "PAID"
    UNKNOWN = "UNKNOWN"
    DISABLED = "DISABLED"


class BaseModelAdapter(ABC):
    """Abstract interface for LLM provider adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the model provider (e.g. 'gemini', 'openai', 'thespark', 'mock')."""
        pass

    @property
    def cost_policy(self) -> CostPolicy:
        """Cost policy classification for this adapter."""
        return CostPolicy.FREE_TIER_ALLOWED

    @property
    def automatic_fallback_allowed(self) -> bool:
        """Whether this provider can be automatically invoked via fallback chain."""
        return True

    @abstractmethod
    def generate(self, request: ModelRequest) -> ModelResponse:
        """Execute a model completion request synchronously."""
        pass

    def generate_stream(self, request: ModelRequest) -> Generator[StreamDelta, None, None]:
        """Execute a model completion request with streaming.

        Yields StreamDelta instances containing visible-only content deltas.
        Default implementation yields STREAM_UNSUPPORTED status.

        Subclasses that support streaming should override this method.
        Non-streaming adapters remain valid through synchronous generate().
        """
        yield StreamDelta(
            content="",
            finish_reason="stream_unsupported",
            provider=self.provider_name,
            model_name=getattr(request, "model_name", "default"),
        )
