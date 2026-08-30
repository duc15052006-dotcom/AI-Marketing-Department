"""Tool Execution Receipts (Phase 5.1).

Defines immutable receipts for every tool execution, enforcing auditability,
security provenance, token/cost attribution, and receipt repositories.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from governance.redaction import (
    REDACTED_SENSITIVE_KEYS,
    sanitize_sensitive_payload,
)
from schemas.base import BaseModel, Field


def sanitize_tool_payload(obj: Any) -> Any:
    """Backward-compatible shared redaction entrypoint for tool payloads."""
    return sanitize_sensitive_payload(obj)


class ExecutionStatus(str, Enum):
    """Lifecycle status of a tool execution."""
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    TIMEOUT = "TIMEOUT"


class ExecutionMode(str, Enum):
    """Execution environment mode for capability runs."""
    REAL = "REAL"
    MOCK = "MOCK"
    SANDBOX = "SANDBOX"


class ExecutionReceipt(BaseModel):
    """Immutable record produced for every capability execution request."""
    execution_id: str = Field(default_factory=lambda: f"EXEC-{uuid.uuid4().hex[:12].upper()}")
    run_id: str = Field(..., description="Unique campaign or workflow run identifier")
    agent_id: str = Field(..., description="Requesting agent (e.g. 'intelligence', 'cmo')")
    capability_id: str = Field(..., description="Executed capability identifier")
    provider: str = Field(..., description="Provider adapter used")
    request_hash: str = Field(..., description="SHA-256 hash of input parameters and context")
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: ExecutionStatus = Field(default=ExecutionStatus.SUCCESS)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.MOCK)
    error_class: Optional[str] = Field(default=None, description="Normalized error category if failed")
    error_message: Optional[str] = Field(default=None)
    cost_or_token_usage: Dict[str, Any] = Field(default_factory=dict)
    artifact_references: List[str] = Field(default_factory=list)
    approval_reference: Optional[str] = Field(default=None, description="Human approval ID or token if required")
    business_id: Optional[str] = Field(default=None, description="Originating business/tenant scope")
    project_id: Optional[str] = Field(default=None, description="Originating project scope")
    chat_id: Optional[str] = Field(default=None, description="Originating chat session scope")
    result_hash: str = Field(default="", description="SHA-256 hash of execution payload data")
    data: Optional[Dict[str, Any]] = Field(default=None)
    output: Any = Field(default=None)
    observation_record: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical serialized ObservationRecord from observation execution path, if available.",
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.error_message is not None:
            self.error_message = sanitize_tool_payload(self.error_message)
        if self.data is not None:
            self.data = sanitize_tool_payload(self.data)
        if self.output is not None:
            self.output = sanitize_tool_payload(self.output)

    def calculate_result_hash(self) -> str:
        """Compute SHA-256 hash of result data."""
        if self.data is None:
            return hashlib.sha256(b"NULL_RESULT").hexdigest()
        raw = json.dumps(self.data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExecutionReceiptRepository:
    """Interface and in-memory/local repository for storing and querying execution receipts."""

    def __init__(self) -> None:
        self._receipts: Dict[str, ExecutionReceipt] = {}

    def save_receipt(self, receipt: ExecutionReceipt) -> ExecutionReceipt:
        """Persist an execution receipt immutably."""
        if not receipt.result_hash and receipt.data is not None:
            receipt.result_hash = receipt.calculate_result_hash()
        self._receipts[receipt.execution_id] = receipt
        return receipt

    def get_receipt(self, execution_id: str) -> Optional[ExecutionReceipt]:
        """Retrieve receipt by execution ID."""
        return self._receipts.get(execution_id)

    def list_receipts_for_run(self, run_id: str) -> List[ExecutionReceipt]:
        """Query all receipts generated during a specific run."""
        return [r for r in self._receipts.values() if r.run_id == run_id]

    def list_receipts_for_agent(self, agent_id: str) -> List[ExecutionReceipt]:
        """Query all receipts for a specific requesting agent."""
        aid = agent_id.lower()
        return [r for r in self._receipts.values() if r.agent_id.lower() == aid]

    def list_receipts_by_status(self, status: ExecutionStatus) -> List[ExecutionReceipt]:
        """Filter receipts by execution status."""
        return [r for r in self._receipts.values() if r.status == status]
