"""Tool execution receipts with immutable, credential-safe payloads."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field

REDACTED_SENSITIVE_KEYS = {
    "api_key", "apikey", "secret", "password", "token", "authorization",
    "auth_token", "access_token", "cookie", "cookies", "credential", "credentials",
    "private_key", "secret_key", "session_token",
}


def _sanitize_string(value: str) -> str:
    redacted = value
    # Redact auth schemes regardless of token length.  Short test/dev tokens
    # must be protected exactly like long production credentials.
    redacted = re.sub(r"(?i)\b(bearer|basic)\s+[^\s,;]+", r"\1 [REDACTED_TOKEN]", redacted)
    redacted = re.sub(r"(?i)(api[_\-]?key\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED_KEY]", redacted)
    redacted = re.sub(r"(?i)(access[_\-]?token\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED_TOKEN]", redacted)
    redacted = re.sub(r"(?i)(secret\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED_SECRET]", redacted)
    return redacted


def sanitize_tool_payload(obj: Any) -> Any:
    """Recursively redact credentials/tokens before any receipt is persisted."""
    if isinstance(obj, dict):
        sanitized: Dict[Any, Any] = {}
        for k, v in obj.items():
            k_str = str(k).lower()
            if k_str in REDACTED_SENSITIVE_KEYS or any(
                s in k_str for s in ("password", "secret", "api_key", "apikey", "auth_token", "access_token", "authorization", "cookie")
            ):
                sanitized[k] = "[REDACTED_SECRET]"
            else:
                sanitized[k] = sanitize_tool_payload(v)
        return sanitized
    if isinstance(obj, list):
        return [sanitize_tool_payload(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_tool_payload(item) for item in obj)
    if isinstance(obj, str):
        return _sanitize_string(obj)
    return obj


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TIMEOUT = "TIMEOUT"


class ExecutionMode(str, Enum):
    REAL = "REAL"
    MOCK = "MOCK"
    SANDBOX = "SANDBOX"


class ExecutionReceipt(BaseModel):
    execution_id: str = Field(default_factory=lambda: f"EXEC-{uuid.uuid4().hex[:12].upper()}")
    run_id: str
    agent_id: str
    capability_id: str
    provider: str
    request_hash: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ExecutionStatus = Field(default=ExecutionStatus.SUCCESS)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.MOCK)
    error_class: Optional[str] = None
    error_message: Optional[str] = None
    cost_or_token_usage: Dict[str, Any] = Field(default_factory=dict)
    artifact_references: List[str] = Field(default_factory=list)
    approval_reference: Optional[str] = None
    business_id: Optional[str] = None
    project_id: Optional[str] = None
    chat_id: Optional[str] = None
    result_hash: str = ""
    data: Optional[Dict[str, Any]] = None
    output: Any = None
    observation_record: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.data is not None:
            self.data = sanitize_tool_payload(self.data)
        if self.output is not None:
            self.output = sanitize_tool_payload(self.output)
        if self.error_message:
            self.error_message = _sanitize_string(str(self.error_message))[:1000]

    def calculate_result_hash(self) -> str:
        if self.data is None:
            return hashlib.sha256(b"NULL_RESULT").hexdigest()
        raw = json.dumps(self.data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExecutionReceiptRepository:
    def __init__(self) -> None:
        self._receipts: Dict[str, ExecutionReceipt] = {}

    def save_receipt(self, receipt: ExecutionReceipt) -> ExecutionReceipt:
        if not receipt.result_hash and receipt.data is not None:
            receipt.result_hash = receipt.calculate_result_hash()
        self._receipts[receipt.execution_id] = receipt
        return receipt

    def get_receipt(self, execution_id: str) -> Optional[ExecutionReceipt]:
        return self._receipts.get(execution_id)

    def list_receipts_for_run(self, run_id: str) -> List[ExecutionReceipt]:
        return [r for r in self._receipts.values() if r.run_id == run_id]

    def list_receipts_for_agent(self, agent_id: str) -> List[ExecutionReceipt]:
        aid = agent_id.lower()
        return [r for r in self._receipts.values() if r.agent_id.lower() == aid]

    def list_receipts_by_status(self, status: ExecutionStatus) -> List[ExecutionReceipt]:
        return [r for r in self._receipts.values() if r.status == status]
