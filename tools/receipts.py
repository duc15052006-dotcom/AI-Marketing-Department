"""Tool execution receipts and durable side-effect intent journal.

The default repository remains in-memory for backward compatibility. Supplying a
``database_path`` enables crash-safe SQLite persistence for receipts and
consequential execution intents. The journal records intent before dispatch so a
restart can distinguish "definitely not dispatched" from an ambiguous external
side effect without replaying the action.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from governance.redaction import sanitize_sensitive_payload, sanitize_sensitive_text
from schemas.base import BaseModel, Field


def sanitize_tool_payload(obj: Any) -> Any:
    """Backward-compatible shared redaction entrypoint for tool payloads."""
    return sanitize_sensitive_payload(obj)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _payload_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _safe_approval_reference(value: Optional[str]) -> Optional[str]:
    """Persist only non-replayable approval references."""
    if not value:
        return None
    if value.startswith("pending_appr_") or value.startswith("approval_ref_"):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"approval_ref_{digest}"


class ReceiptStoreError(RuntimeError):
    """Base error raised by receipt/intent durability storage."""


class ReceiptStoreIntegrityError(ReceiptStoreError):
    """Raised when persisted receipt or intent data fails integrity checks."""


class ReceiptStoreConflictError(ReceiptStoreError):
    """Raised when immutable receipt/intent state would be overwritten."""


def _sqlite_failure(operation: str, exc: sqlite3.Error) -> ReceiptStoreError:
    safe = sanitize_sensitive_text(str(exc))
    return ReceiptStoreError(f"RECEIPT_STORE_{operation}_FAILED: {safe}")


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


class ExecutionIntentState(str, Enum):
    """Durable lifecycle for a consequential external action."""

    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    FINALIZED = "FINALIZED"
    AMBIGUOUS = "AMBIGUOUS"


class ReconciliationOutcome(str, Enum):
    """Evidence-only side-effect reconciliation classification."""

    NOT_DISPATCHED = "NOT_DISPATCHED"
    CONFIRMED_FINALIZED = "CONFIRMED_FINALIZED"
    AMBIGUOUS_EXTERNAL_ACTION_OUTCOME = "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class ExecutionReceipt(BaseModel):
    """Immutable record produced for every capability execution request."""

    execution_id: str = Field(default_factory=lambda: f"EXEC-{uuid.uuid4().hex[:12].upper()}")
    run_id: str = Field(..., description="Unique campaign or workflow run identifier")
    agent_id: str = Field(..., description="Requesting agent (e.g. 'intelligence', 'cmo')")
    capability_id: str = Field(..., description="Executed capability identifier")
    provider: str = Field(..., description="Provider adapter used")
    request_hash: str = Field(..., description="SHA-256 hash of input parameters and context")
    started_at: datetime = Field(default_factory=_utc_now)
    completed_at: datetime = Field(default_factory=_utc_now)
    status: ExecutionStatus = Field(default=ExecutionStatus.SUCCESS)
    execution_mode: ExecutionMode = Field(default=ExecutionMode.MOCK)
    error_class: Optional[str] = Field(default=None, description="Normalized error category if failed")
    error_message: Optional[str] = Field(default=None)
    cost_or_token_usage: Dict[str, Any] = Field(default_factory=dict)
    artifact_references: List[str] = Field(default_factory=list)
    approval_reference: Optional[str] = Field(default=None, description="Non-replayable approval audit reference")
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


@dataclass(frozen=True)
class ExecutionIntent:
    """Persisted pre-dispatch evidence for one consequential tool action."""

    intent_id: str
    request_id: str
    run_id: str
    agent_id: str
    capability_id: str
    provider: str
    request_hash: str
    state: ExecutionIntentState = ExecutionIntentState.PREPARED
    business_id: Optional[str] = None
    project_id: Optional[str] = None
    chat_id: Optional[str] = None
    approval_reference: Optional[str] = None
    dispatch_count: int = 0
    receipt_execution_id: Optional[str] = None
    last_error_class: Optional[str] = None
    last_error_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    schema_version: int = 1
    record_hash: str = ""

    def normalized(self) -> "ExecutionIntent":
        required = {
            "intent_id": self.intent_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "capability_id": self.capability_id,
            "provider": self.provider,
            "request_hash": self.request_hash,
        }
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name.upper()}_REQUIRED: execution intent {name} is required")
        if not isinstance(self.dispatch_count, int) or isinstance(self.dispatch_count, bool) or self.dispatch_count < 0:
            raise ValueError("INVALID_DISPATCH_COUNT: dispatch_count must be a non-negative integer")

        state = self.state
        if not isinstance(state, ExecutionIntentState):
            state = ExecutionIntentState(str(state).strip().upper())

        created_at = self.created_at or _utc_now_iso()
        normalized = replace(
            self,
            intent_id=self.intent_id.strip(),
            request_id=self.request_id.strip(),
            run_id=self.run_id.strip(),
            agent_id=self.agent_id.strip(),
            capability_id=self.capability_id.strip(),
            provider=self.provider.strip(),
            request_hash=self.request_hash.strip(),
            state=state,
            approval_reference=_safe_approval_reference(self.approval_reference),
            last_error_class=sanitize_sensitive_text(self.last_error_class) if self.last_error_class else None,
            last_error_message=sanitize_sensitive_text(self.last_error_message) if self.last_error_message else None,
            created_at=created_at,
            updated_at=self.updated_at or created_at,
            record_hash="",
        )
        return replace(normalized, record_hash=normalized.calculate_hash())

    def hash_payload(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "capability_id": self.capability_id,
            "provider": self.provider,
            "request_hash": self.request_hash,
            "state": self.state.value if isinstance(self.state, ExecutionIntentState) else str(self.state),
            "business_id": self.business_id,
            "project_id": self.project_id,
            "chat_id": self.chat_id,
            "approval_reference": self.approval_reference,
            "dispatch_count": self.dispatch_count,
            "receipt_execution_id": self.receipt_execution_id,
            "last_error_class": self.last_error_class,
            "last_error_message": self.last_error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def calculate_hash(self) -> str:
        return _payload_hash(self.hash_payload())

    def verify_integrity(self) -> bool:
        return bool(self.record_hash) and self.record_hash == self.calculate_hash()


@dataclass(frozen=True)
class ReconciliationAssessment:
    """Evidence classification only; never an instruction to replay a tool action."""

    intent_id: str
    outcome: ReconciliationOutcome
    receipt_execution_id: Optional[str] = None
    reason: str = ""


def _receipt_from_payload(payload: Dict[str, Any]) -> ExecutionReceipt:
    data = dict(payload)
    for key in ("started_at", "completed_at"):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = datetime.fromisoformat(value)
    if not isinstance(data.get("status"), ExecutionStatus):
        data["status"] = ExecutionStatus(str(data["status"]).strip().upper())
    if not isinstance(data.get("execution_mode"), ExecutionMode):
        data["execution_mode"] = ExecutionMode(str(data["execution_mode"]).strip().upper())
    return ExecutionReceipt(**data)


def _normalize_receipt(receipt: ExecutionReceipt) -> ExecutionReceipt:
    payload = sanitize_sensitive_payload(receipt.model_dump())
    payload["approval_reference"] = _safe_approval_reference(payload.get("approval_reference"))
    normalized = _receipt_from_payload(payload)
    if not normalized.result_hash and normalized.data is not None:
        normalized.result_hash = normalized.calculate_result_hash()
    return normalized


def _receipt_matches_intent_binding(receipt: ExecutionReceipt, intent: ExecutionIntent) -> bool:
    """Require exact agreement across immutable execution authority dimensions."""
    return (
        receipt.run_id == intent.run_id
        and receipt.agent_id == intent.agent_id
        and receipt.capability_id == intent.capability_id
        and receipt.provider == intent.provider
        and receipt.request_hash == intent.request_hash
        and receipt.business_id == intent.business_id
        and receipt.project_id == intent.project_id
        and receipt.chat_id == intent.chat_id
        and receipt.approval_reference == intent.approval_reference
    )


class ExecutionReceiptRepository:
    """Receipt repository with optional crash-safe SQLite durability.

    ``ExecutionReceiptRepository()`` preserves the historic in-memory behavior.
    ``ExecutionReceiptRepository(database_path=...)`` enables durable receipts and
    a pre-dispatch journal for consequential external actions.
    """

    def __init__(self, database_path: Optional[str | Path] = None) -> None:
        self._lock = threading.RLock()
        self._receipts: Dict[str, ExecutionReceipt] = {}
        self._intents: Dict[str, ExecutionIntent] = {}
        self.database_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None
        self._closed = False

        if database_path is not None:
            raw_path = str(database_path)
            if raw_path == ":memory:":
                db_target = raw_path
            else:
                self.database_path = Path(database_path).expanduser().resolve()
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                db_target = str(self.database_path)
            self._conn = sqlite3.connect(db_target, timeout=5.0, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            try:
                with self._lock:
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA synchronous=FULL")
                    self._conn.execute("PRAGMA foreign_keys=ON")
                    self._conn.execute("PRAGMA busy_timeout=5000")
                    self._initialize_schema()
            except sqlite3.Error as exc:
                raise _sqlite_failure("INIT", exc) from exc

    @property
    def durable(self) -> bool:
        return self._conn is not None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ReceiptStoreError("RECEIPT_STORE_CLOSED: repository is closed")

    def _initialize_schema(self) -> None:
        assert self._conn is not None
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_receipts (
                    execution_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    payload_hash TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_intents (
                    intent_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    business_id TEXT,
                    project_id TEXT,
                    chat_id TEXT,
                    approval_reference TEXT,
                    dispatch_count INTEGER NOT NULL DEFAULT 0,
                    receipt_execution_id TEXT,
                    last_error_class TEXT,
                    last_error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    record_hash TEXT NOT NULL,
                    FOREIGN KEY(receipt_execution_id) REFERENCES execution_receipts(execution_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_receipts_run ON execution_receipts(run_id, execution_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_receipts_agent ON execution_receipts(agent_id, execution_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_receipts_status ON execution_receipts(status, execution_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intents_run ON execution_intents(run_id, intent_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intents_state ON execution_intents(state, intent_id)"
            )

    @staticmethod
    def _receipt_payload(receipt: ExecutionReceipt) -> tuple[ExecutionReceipt, Dict[str, Any], str]:
        normalized = _normalize_receipt(receipt)
        payload = normalized.model_dump()
        return normalized, payload, _payload_hash(payload)

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> ExecutionIntent:
        intent = ExecutionIntent(
            intent_id=row["intent_id"],
            request_id=row["request_id"],
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            capability_id=row["capability_id"],
            provider=row["provider"],
            request_hash=row["request_hash"],
            state=ExecutionIntentState(row["state"]),
            business_id=row["business_id"],
            project_id=row["project_id"],
            chat_id=row["chat_id"],
            approval_reference=row["approval_reference"],
            dispatch_count=int(row["dispatch_count"]),
            receipt_execution_id=row["receipt_execution_id"],
            last_error_class=row["last_error_class"],
            last_error_message=row["last_error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            schema_version=int(row["schema_version"]),
            record_hash=row["record_hash"],
        )
        if not intent.verify_integrity():
            raise ReceiptStoreIntegrityError(
                f"EXECUTION_INTENT_INTEGRITY_MISMATCH: intent_id={intent.intent_id}"
            )
        return intent

    @staticmethod
    def _decode_receipt_row(row: sqlite3.Row) -> ExecutionReceipt:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReceiptStoreIntegrityError(
                f"EXECUTION_RECEIPT_INVALID_JSON: execution_id={row['execution_id']}"
            ) from exc
        if _payload_hash(payload) != row["payload_hash"]:
            raise ReceiptStoreIntegrityError(
                f"EXECUTION_RECEIPT_INTEGRITY_MISMATCH: execution_id={row['execution_id']}"
            )
        receipt = _receipt_from_payload(payload)
        if receipt.execution_id != row["execution_id"]:
            raise ReceiptStoreIntegrityError(
                f"EXECUTION_RECEIPT_ID_MISMATCH: execution_id={row['execution_id']}"
            )
        indexed_metadata = {
            "run_id": receipt.run_id,
            "agent_id": receipt.agent_id,
            "capability_id": receipt.capability_id,
            "status": receipt.status.value,
        }
        for field, payload_value in indexed_metadata.items():
            if row[field] != payload_value:
                raise ReceiptStoreIntegrityError(
                    f"EXECUTION_RECEIPT_INDEX_METADATA_MISMATCH: "
                    f"execution_id={row['execution_id']} field={field}"
                )
        return receipt

    @staticmethod
    def _intent_values(intent: ExecutionIntent) -> tuple[Any, ...]:
        return (
            intent.intent_id,
            intent.request_id,
            intent.run_id,
            intent.agent_id,
            intent.capability_id,
            intent.provider,
            intent.request_hash,
            intent.state.value,
            intent.business_id,
            intent.project_id,
            intent.chat_id,
            intent.approval_reference,
            intent.dispatch_count,
            intent.receipt_execution_id,
            intent.last_error_class,
            intent.last_error_message,
            intent.created_at,
            intent.updated_at,
            intent.schema_version,
            intent.record_hash,
        )

    def _insert_receipt_locked(self, receipt: ExecutionReceipt) -> ExecutionReceipt:
        normalized, payload, digest = self._receipt_payload(receipt)
        if self._conn is None:
            existing = self._receipts.get(normalized.execution_id)
            if existing is not None:
                _, existing_payload, _ = self._receipt_payload(existing)
                if _payload_hash(existing_payload) != digest:
                    raise ReceiptStoreConflictError(
                        f"EXECUTION_RECEIPT_IMMUTABLE_CONFLICT: execution_id={normalized.execution_id}"
                    )
                return copy.deepcopy(existing)
            self._receipts[normalized.execution_id] = copy.deepcopy(normalized)
            return copy.deepcopy(normalized)

        existing = self._conn.execute(
            "SELECT payload_hash, payload_json FROM execution_receipts WHERE execution_id=?",
            (normalized.execution_id,),
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != digest:
                raise ReceiptStoreConflictError(
                    f"EXECUTION_RECEIPT_IMMUTABLE_CONFLICT: execution_id={normalized.execution_id}"
                )
            return self._decode_receipt_row(
                self._conn.execute(
                    "SELECT * FROM execution_receipts WHERE execution_id=?",
                    (normalized.execution_id,),
                ).fetchone()
            )
        self._conn.execute(
            """
            INSERT INTO execution_receipts(
                execution_id, run_id, agent_id, capability_id, status, payload_json, payload_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized.execution_id,
                normalized.run_id,
                normalized.agent_id,
                normalized.capability_id,
                normalized.status.value,
                _canonical_json(payload),
                digest,
            ),
        )
        return normalized

    def save_receipt(self, receipt: ExecutionReceipt) -> ExecutionReceipt:
        """Persist a receipt immutably and return a defensive copy."""
        self._ensure_open()
        with self._lock:
            try:
                if self._conn is None:
                    return self._insert_receipt_locked(receipt)
                with self._conn:
                    stored = self._insert_receipt_locked(receipt)
                return copy.deepcopy(stored)
            except ReceiptStoreError:
                raise
            except sqlite3.Error as exc:
                raise _sqlite_failure("SAVE_RECEIPT", exc) from exc

    def get_receipt(self, execution_id: str) -> Optional[ExecutionReceipt]:
        self._ensure_open()
        with self._lock:
            if self._conn is None:
                receipt = self._receipts.get(execution_id)
                return copy.deepcopy(receipt) if receipt is not None else None
            try:
                row = self._conn.execute(
                    "SELECT * FROM execution_receipts WHERE execution_id=?",
                    (execution_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise _sqlite_failure("GET_RECEIPT", exc) from exc
            return self._decode_receipt_row(row) if row is not None else None

    def _list_receipts(self, where: str, value: Any) -> List[ExecutionReceipt]:
        self._ensure_open()
        with self._lock:
            if self._conn is None:
                receipts = list(self._receipts.values())
                if where == "run_id":
                    receipts = [r for r in receipts if r.run_id == value]
                elif where == "agent_id":
                    receipts = [r for r in receipts if r.agent_id.lower() == str(value).lower()]
                elif where == "status":
                    receipts = [r for r in receipts if r.status == value]
                return copy.deepcopy(receipts)
            try:
                query_value = value.value if isinstance(value, Enum) else value
                rows = self._conn.execute(
                    f"SELECT * FROM execution_receipts WHERE {where}=? ORDER BY rowid",
                    (query_value,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise _sqlite_failure("LIST_RECEIPTS", exc) from exc
            return [self._decode_receipt_row(row) for row in rows]

    def list_receipts_for_run(self, run_id: str) -> List[ExecutionReceipt]:
        return self._list_receipts("run_id", run_id)

    def list_receipts_for_agent(self, agent_id: str) -> List[ExecutionReceipt]:
        self._ensure_open()
        if self._conn is None:
            return self._list_receipts("agent_id", agent_id)
        with self._lock:
            try:
                rows = self._conn.execute(
                    "SELECT * FROM execution_receipts WHERE lower(agent_id)=lower(?) ORDER BY rowid",
                    (agent_id,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise _sqlite_failure("LIST_RECEIPTS", exc) from exc
            return [self._decode_receipt_row(row) for row in rows]

    def list_receipts_by_status(self, status: ExecutionStatus) -> List[ExecutionReceipt]:
        return self._list_receipts("status", status)

    def prepare_execution_intent(
        self,
        *,
        request_id: str,
        run_id: str,
        agent_id: str,
        capability_id: str,
        provider: str,
        request_hash: str,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        approval_reference: Optional[str] = None,
    ) -> ExecutionIntent:
        """Persist PREPARED evidence before any consequential adapter dispatch."""
        self._ensure_open()
        intent = ExecutionIntent(
            intent_id=f"INTENT-{uuid.uuid4().hex[:16].upper()}",
            request_id=request_id,
            run_id=run_id,
            agent_id=agent_id,
            capability_id=capability_id,
            provider=provider,
            request_hash=request_hash,
            business_id=business_id,
            project_id=project_id,
            chat_id=chat_id,
            approval_reference=approval_reference,
        ).normalized()

        with self._lock:
            try:
                if self._conn is None:
                    self._intents[intent.intent_id] = intent
                    return copy.deepcopy(intent)
                with self._conn:
                    self._conn.execute(
                        """
                        INSERT INTO execution_intents(
                            intent_id, request_id, run_id, agent_id, capability_id, provider,
                            request_hash, state, business_id, project_id, chat_id,
                            approval_reference, dispatch_count, receipt_execution_id,
                            last_error_class, last_error_message, created_at, updated_at,
                            schema_version, record_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._intent_values(intent),
                    )
                return intent
            except sqlite3.IntegrityError as exc:
                raise ReceiptStoreConflictError(
                    f"EXECUTION_INTENT_ALREADY_EXISTS: intent_id={intent.intent_id}"
                ) from exc
            except sqlite3.Error as exc:
                raise _sqlite_failure("PREPARE_INTENT", exc) from exc

    def get_execution_intent(self, intent_id: str) -> Optional[ExecutionIntent]:
        self._ensure_open()
        with self._lock:
            if self._conn is None:
                intent = self._intents.get(intent_id)
                return copy.deepcopy(intent) if intent is not None else None
            try:
                row = self._conn.execute(
                    "SELECT * FROM execution_intents WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise _sqlite_failure("GET_INTENT", exc) from exc
            return self._intent_from_row(row) if row is not None else None

    def list_execution_intents_for_run(self, run_id: str) -> List[ExecutionIntent]:
        self._ensure_open()
        with self._lock:
            if self._conn is None:
                return copy.deepcopy([i for i in self._intents.values() if i.run_id == run_id])
            try:
                rows = self._conn.execute(
                    "SELECT * FROM execution_intents WHERE run_id=? ORDER BY rowid",
                    (run_id,),
                ).fetchall()
            except sqlite3.Error as exc:
                raise _sqlite_failure("LIST_INTENTS", exc) from exc
            return [self._intent_from_row(row) for row in rows]

    def _replace_intent_locked(self, intent: ExecutionIntent) -> ExecutionIntent:
        normalized = intent.normalized()
        if self._conn is None:
            if normalized.intent_id not in self._intents:
                raise ReceiptStoreConflictError(
                    f"EXECUTION_INTENT_NOT_FOUND: intent_id={normalized.intent_id}"
                )
            self._intents[normalized.intent_id] = normalized
            return normalized

        cur = self._conn.execute(
            """
            UPDATE execution_intents SET
                request_id=?, run_id=?, agent_id=?, capability_id=?, provider=?,
                request_hash=?, state=?, business_id=?, project_id=?, chat_id=?,
                approval_reference=?, dispatch_count=?, receipt_execution_id=?,
                last_error_class=?, last_error_message=?, created_at=?, updated_at=?,
                schema_version=?, record_hash=?
            WHERE intent_id=?
            """,
            (
                normalized.request_id,
                normalized.run_id,
                normalized.agent_id,
                normalized.capability_id,
                normalized.provider,
                normalized.request_hash,
                normalized.state.value,
                normalized.business_id,
                normalized.project_id,
                normalized.chat_id,
                normalized.approval_reference,
                normalized.dispatch_count,
                normalized.receipt_execution_id,
                normalized.last_error_class,
                normalized.last_error_message,
                normalized.created_at,
                normalized.updated_at,
                normalized.schema_version,
                normalized.record_hash,
                normalized.intent_id,
            ),
        )
        if cur.rowcount != 1:
            raise ReceiptStoreConflictError(
                f"EXECUTION_INTENT_NOT_FOUND: intent_id={normalized.intent_id}"
            )
        return normalized

    def mark_execution_intent_dispatching(self, intent_id: str) -> ExecutionIntent:
        """Persist DISPATCHING before entering adapter code."""
        self._ensure_open()
        with self._lock:
            try:
                current = self.get_execution_intent(intent_id)
                if current is None:
                    raise ReceiptStoreConflictError(
                        f"EXECUTION_INTENT_NOT_FOUND: intent_id={intent_id}"
                    )
                if current.state != ExecutionIntentState.PREPARED or current.dispatch_count != 0:
                    raise ReceiptStoreConflictError(
                        f"EXECUTION_INTENT_INVALID_DISPATCH_TRANSITION: intent_id={intent_id} "
                        f"state={current.state.value} dispatch_count={current.dispatch_count}"
                    )
                updated = replace(
                    current,
                    state=ExecutionIntentState.DISPATCHING,
                    dispatch_count=1,
                    updated_at=_utc_now_iso(),
                    record_hash="",
                )
                if self._conn is None:
                    return copy.deepcopy(self._replace_intent_locked(updated))
                with self._conn:
                    stored = self._replace_intent_locked(updated)
                return copy.deepcopy(stored)
            except ReceiptStoreError:
                raise
            except sqlite3.Error as exc:
                raise _sqlite_failure("MARK_DISPATCHING", exc) from exc

    def finalize_execution_intent(
        self,
        intent_id: str,
        receipt: ExecutionReceipt,
        *,
        ambiguous: bool = False,
    ) -> ExecutionReceipt:
        """Atomically persist receipt and settle the associated intent."""
        self._ensure_open()
        with self._lock:
            try:
                current = self.get_execution_intent(intent_id)
                if current is None:
                    raise ReceiptStoreConflictError(
                        f"EXECUTION_INTENT_NOT_FOUND: intent_id={intent_id}"
                    )
                normalized_receipt, _, _ = self._receipt_payload(receipt)
                if not _receipt_matches_intent_binding(normalized_receipt, current):
                    raise ReceiptStoreIntegrityError(
                        f"EXECUTION_INTENT_RECEIPT_BINDING_MISMATCH: intent_id={intent_id}"
                    )

                target_state = (
                    ExecutionIntentState.AMBIGUOUS if ambiguous else ExecutionIntentState.FINALIZED
                )
                if current.state in (ExecutionIntentState.FINALIZED, ExecutionIntentState.AMBIGUOUS):
                    if (
                        current.state != target_state
                        or current.receipt_execution_id != normalized_receipt.execution_id
                    ):
                        raise ReceiptStoreConflictError(
                            f"EXECUTION_INTENT_IMMUTABLE_CONFLICT: intent_id={intent_id}"
                        )
                    existing = self.get_receipt(normalized_receipt.execution_id)
                    if existing is None:
                        raise ReceiptStoreIntegrityError(
                            f"EXECUTION_INTENT_RECEIPT_MISSING: intent_id={intent_id}"
                        )
                    self._insert_receipt_locked(normalized_receipt)
                    return existing

                if current.state != ExecutionIntentState.DISPATCHING or current.dispatch_count < 1:
                    raise ReceiptStoreConflictError(
                        f"EXECUTION_INTENT_INVALID_FINALIZE_TRANSITION: intent_id={intent_id} "
                        f"state={current.state.value}"
                    )

                updated = replace(
                    current,
                    state=target_state,
                    receipt_execution_id=normalized_receipt.execution_id,
                    last_error_class=normalized_receipt.error_class,
                    last_error_message=normalized_receipt.error_message,
                    updated_at=_utc_now_iso(),
                    record_hash="",
                )
                if self._conn is None:
                    stored_receipt = self._insert_receipt_locked(normalized_receipt)
                    self._replace_intent_locked(updated)
                    return copy.deepcopy(stored_receipt)

                with self._conn:
                    stored_receipt = self._insert_receipt_locked(normalized_receipt)
                    self._replace_intent_locked(updated)
                return copy.deepcopy(stored_receipt)
            except ReceiptStoreError:
                raise
            except sqlite3.Error as exc:
                raise _sqlite_failure("FINALIZE_INTENT", exc) from exc

    def assess_execution_intent(self, intent_id: str) -> ReconciliationAssessment:
        """Classify persisted evidence without dispatching or retrying anything."""
        self._ensure_open()
        intent = self.get_execution_intent(intent_id)
        if intent is None:
            return ReconciliationAssessment(
                intent_id=intent_id,
                outcome=ReconciliationOutcome.INSUFFICIENT_EVIDENCE,
                reason="No durable execution intent exists for this identifier.",
            )

        receipt = (
            self.get_receipt(intent.receipt_execution_id)
            if intent.receipt_execution_id
            else None
        )
        if intent.state == ExecutionIntentState.PREPARED and intent.dispatch_count == 0:
            if receipt is not None:
                raise ReceiptStoreIntegrityError(
                    f"PREPARED_INTENT_HAS_RECEIPT: intent_id={intent_id}"
                )
            return ReconciliationAssessment(
                intent_id=intent_id,
                outcome=ReconciliationOutcome.NOT_DISPATCHED,
                reason="Durable intent remained PREPARED with dispatch_count=0.",
            )

        if intent.state == ExecutionIntentState.AMBIGUOUS:
            if intent.receipt_execution_id and receipt is None:
                raise ReceiptStoreIntegrityError(
                    f"AMBIGUOUS_INTENT_RECEIPT_MISSING: intent_id={intent_id}"
                )
            if receipt is not None and not _receipt_matches_intent_binding(receipt, intent):
                raise ReceiptStoreIntegrityError(
                    f"AMBIGUOUS_INTENT_RECEIPT_BINDING_MISMATCH: intent_id={intent_id}"
                )
            return ReconciliationAssessment(
                intent_id=intent_id,
                outcome=ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
                receipt_execution_id=intent.receipt_execution_id,
                reason="External side-effect outcome is intentionally classified as ambiguous; automatic replay is forbidden.",
            )

        if intent.state == ExecutionIntentState.DISPATCHING:
            if receipt is not None:
                raise ReceiptStoreIntegrityError(
                    f"DISPATCHING_INTENT_HAS_LINKED_RECEIPT: intent_id={intent_id}"
                )
            return ReconciliationAssessment(
                intent_id=intent_id,
                outcome=ReconciliationOutcome.AMBIGUOUS_EXTERNAL_ACTION_OUTCOME,
                reason="Dispatch began but no final receipt exists; absence of a receipt does not prove the external action did not run.",
            )

        if intent.state == ExecutionIntentState.FINALIZED:
            if receipt is None:
                raise ReceiptStoreIntegrityError(
                    f"FINALIZED_INTENT_RECEIPT_MISSING: intent_id={intent_id}"
                )
            if not _receipt_matches_intent_binding(receipt, intent):
                raise ReceiptStoreIntegrityError(
                    f"FINALIZED_INTENT_RECEIPT_BINDING_MISMATCH: intent_id={intent_id}"
                )
            return ReconciliationAssessment(
                intent_id=intent_id,
                outcome=ReconciliationOutcome.CONFIRMED_FINALIZED,
                receipt_execution_id=receipt.execution_id,
                reason="Durable intent and immutable receipt are integrity-bound and finalized.",
            )

        return ReconciliationAssessment(
            intent_id=intent_id,
            outcome=ReconciliationOutcome.INSUFFICIENT_EVIDENCE,
            reason="Persisted execution state is not classifiable.",
        )

    def reconcile_unfinished_intents(self) -> List[ReconciliationAssessment]:
        """On restart, conservatively seal DISPATCHING intents as AMBIGUOUS.

        PREPARED intents remain PREPARED because they are durable evidence that
        adapter dispatch had not begun. This method never invokes a tool adapter.
        """
        self._ensure_open()
        assessments: List[ReconciliationAssessment] = []
        with self._lock:
            if self._conn is None:
                candidates = list(self._intents.values())
            else:
                try:
                    rows = self._conn.execute(
                        "SELECT * FROM execution_intents WHERE state IN (?, ?) ORDER BY rowid",
                        (
                            ExecutionIntentState.PREPARED.value,
                            ExecutionIntentState.DISPATCHING.value,
                        ),
                    ).fetchall()
                except sqlite3.Error as exc:
                    raise _sqlite_failure("RECONCILE_INTENTS", exc) from exc
                candidates = [self._intent_from_row(row) for row in rows]

            for intent in candidates:
                if intent.state == ExecutionIntentState.DISPATCHING:
                    updated = replace(
                        intent,
                        state=ExecutionIntentState.AMBIGUOUS,
                        last_error_class="AMBIGUOUS_EXTERNAL_ACTION_OUTCOME",
                        last_error_message=(
                            "Recovered after dispatch began without a finalized receipt; "
                            "automatic replay is forbidden."
                        ),
                        updated_at=_utc_now_iso(),
                        record_hash="",
                    )
                    try:
                        if self._conn is None:
                            self._replace_intent_locked(updated)
                        else:
                            with self._conn:
                                self._replace_intent_locked(updated)
                    except sqlite3.Error as exc:
                        raise _sqlite_failure("RECONCILE_INTENTS", exc) from exc
                assessments.append(self.assess_execution_intent(intent.intent_id))
        return assessments

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            if self._conn is not None:
                self._conn.close()
            self._closed = True