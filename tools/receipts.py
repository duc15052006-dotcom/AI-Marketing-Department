"""Mission-aware compatibility facade for the durable execution receipt journal.

The durable receipt/intent implementation is the qualified foundation from the
platform hardening stack, retained byte-for-byte in :mod:`tools.receipts_core`.
This facade extends that authority with optional Mission/Commitment lineage while
preserving historical schema-v1/v2 intent hashes and legacy unbound receipt
payloads.
"""

from __future__ import annotations

import copy
import sqlite3
import uuid
from dataclasses import dataclass, replace
from typing import Any, Dict, Optional

from schemas.base import Field
from tools import receipts_core as _core
from tools.receipts_core import *  # noqa: F401,F403 - preserve the established module surface


_BaseExecutionReceipt = _core.ExecutionReceipt
_BaseExecutionIntent = _core.ExecutionIntent
_BaseExecutionReceiptRepository = _core.ExecutionReceiptRepository
_base_receipt_matches_intent_binding = _core._receipt_matches_intent_binding


class ExecutionReceipt(_BaseExecutionReceipt):
    """Execution receipt with optional exact Mission/Commitment provenance."""

    mission_id: Optional[str] = Field(
        default=None,
        description="Originating durable Mission identity when Mission-bound",
    )
    commitment_id: Optional[str] = Field(
        default=None,
        description="Originating Mission commitment identity when Mission-bound",
    )

    def __post_init__(self) -> None:
        super().__post_init__()
        has_mission = self.mission_id is not None
        has_commitment = self.commitment_id is not None
        if has_mission != has_commitment:
            raise ValueError("EXECUTION_RECEIPT_MISSION_COMMITMENT_LINEAGE_INCOMPLETE")
        if has_mission:
            if not isinstance(self.mission_id, str) or not self.mission_id.strip():
                raise ValueError("EXECUTION_RECEIPT_MISSION_ID_REQUIRED")
            if not isinstance(self.commitment_id, str) or not self.commitment_id.strip():
                raise ValueError("EXECUTION_RECEIPT_COMMITMENT_ID_REQUIRED")
            self.mission_id = self.mission_id.strip()
            self.commitment_id = self.commitment_id.strip()


@dataclass(frozen=True)
class ExecutionIntent(_BaseExecutionIntent):
    """Execution intent with schema-v3 Mission/Commitment authority binding."""

    mission_id: Optional[str] = None
    commitment_id: Optional[str] = None

    def normalized(self) -> "ExecutionIntent":
        prepared = self
        if self.schema_version >= 3:
            if not isinstance(self.mission_id, str) or not self.mission_id.strip():
                raise ValueError(
                    "MISSION_ID_REQUIRED: schema v3 execution intents must bind mission_id"
                )
            if not isinstance(self.commitment_id, str) or not self.commitment_id.strip():
                raise ValueError(
                    "COMMITMENT_ID_REQUIRED: schema v3 execution intents must bind commitment_id"
                )
            prepared = replace(
                self,
                mission_id=self.mission_id.strip(),
                commitment_id=self.commitment_id.strip(),
                record_hash="",
            )
        elif self.mission_id is not None or self.commitment_id is not None:
            raise ValueError(
                "MISSION_LINEAGE_REQUIRES_SCHEMA_V3: historical intent schemas cannot claim Mission authority"
            )
        return _BaseExecutionIntent.normalized(prepared)

    def hash_payload(self) -> Dict[str, Any]:
        payload = _BaseExecutionIntent.hash_payload(self)
        if self.schema_version >= 3:
            payload["mission_id"] = self.mission_id
            payload["commitment_id"] = self.commitment_id
        return payload


def _receipt_matches_intent_binding(
    receipt: ExecutionReceipt,
    intent: ExecutionIntent,
) -> bool:
    """Require exact legacy authority plus schema-v3 Mission lineage."""

    if not _base_receipt_matches_intent_binding(receipt, intent):
        return False
    if intent.schema_version >= 3:
        return (
            receipt.mission_id == intent.mission_id
            and receipt.commitment_id == intent.commitment_id
        )
    return receipt.mission_id is None and receipt.commitment_id is None


class _DurableReceiptCompatibilityIndex(dict):
    """Legacy private receipt view backed by the authoritative SQLite store.

    Older callers still read ``repository._receipts.values()``.  Once the
    repository is durable that in-memory dictionary is no longer authoritative,
    so expose a live read-through view instead of mirroring durable rows into a
    second cache.  New code should call ``list_receipts()``.
    """

    def __init__(self, repository: "ExecutionReceiptRepository") -> None:
        super().__init__()
        self._repository = repository

    def values(self):  # type: ignore[override]
        return self._repository.list_receipts()

    def get(self, key: object, default: Any = None) -> Any:  # type: ignore[override]
        if not isinstance(key, str):
            return default
        receipt = self._repository.get_receipt(key)
        return receipt if receipt is not None else default


class ExecutionReceiptRepository(_BaseExecutionReceiptRepository):
    """Durable receipt journal extended with backward-compatible Mission lineage."""

    def __init__(self, database_path: Optional[str | _core.Path] = None) -> None:
        super().__init__(database_path=database_path)
        if self.durable:
            # Keep legacy private readers correct without making the compatibility
            # dictionary a second source of truth.
            self._receipts = _DurableReceiptCompatibilityIndex(self)

    def _initialize_schema(self) -> None:
        super()._initialize_schema()
        assert self._conn is not None
        intent_columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(execution_intents)").fetchall()
        }
        with self._conn:
            if "mission_id" not in intent_columns:
                self._conn.execute(
                    "ALTER TABLE execution_intents ADD COLUMN mission_id TEXT"
                )
            if "commitment_id" not in intent_columns:
                self._conn.execute(
                    "ALTER TABLE execution_intents ADD COLUMN commitment_id TEXT"
                )

    def list_receipts(self) -> list[ExecutionReceipt]:
        """Return all receipts from the authoritative backing store."""

        self._ensure_open()
        with self._lock:
            if self._conn is None:
                return copy.deepcopy(list(self._receipts.values()))
            try:
                rows = self._conn.execute(
                    "SELECT * FROM execution_receipts ORDER BY rowid"
                ).fetchall()
            except sqlite3.Error as exc:
                raise _core._sqlite_failure("LIST_RECEIPTS", exc) from exc
            return [self._decode_receipt_row(row) for row in rows]

    @staticmethod
    def _receipt_payload(receipt: ExecutionReceipt) -> tuple[ExecutionReceipt, Dict[str, Any], str]:
        normalized = _core._normalize_receipt(receipt)
        payload = normalized.model_dump()
        if normalized.mission_id is None and normalized.commitment_id is None:
            # Preserve the exact historical payload/hash shape for unbound receipts.
            payload.pop("mission_id", None)
            payload.pop("commitment_id", None)
        return normalized, payload, _core._payload_hash(payload)

    @staticmethod
    def _intent_from_row(row: sqlite3.Row) -> ExecutionIntent:
        raw_execution_mode = row["execution_mode"]
        intent = ExecutionIntent(
            intent_id=row["intent_id"],
            request_id=row["request_id"],
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            capability_id=row["capability_id"],
            provider=row["provider"],
            request_hash=row["request_hash"],
            execution_mode=(
                ExecutionMode(str(raw_execution_mode).strip().upper())
                if raw_execution_mode is not None
                else None
            ),
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
            mission_id=row["mission_id"],
            commitment_id=row["commitment_id"],
        )
        if not intent.verify_integrity():
            raise ReceiptStoreIntegrityError(
                f"EXECUTION_INTENT_INTEGRITY_MISMATCH: intent_id={intent.intent_id}"
            )
        return intent

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
            intent.execution_mode.value if intent.execution_mode is not None else None,
            intent.state.value,
            intent.business_id,
            intent.project_id,
            intent.mission_id,
            intent.commitment_id,
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

    def prepare_execution_intent(
        self,
        *,
        request_id: str,
        run_id: str,
        agent_id: str,
        capability_id: str,
        provider: str,
        request_hash: str,
        execution_mode: ExecutionMode = ExecutionMode.MOCK,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        approval_reference: Optional[str] = None,
        mission_id: Optional[str] = None,
        commitment_id: Optional[str] = None,
    ) -> ExecutionIntent:
        """Persist PREPARED evidence, using schema v3 only for Mission-bound work."""

        self._ensure_open()
        lineage_requested = mission_id is not None or commitment_id is not None
        intent = ExecutionIntent(
            intent_id=f"INTENT-{uuid.uuid4().hex[:16].upper()}",
            request_id=request_id,
            run_id=run_id,
            agent_id=agent_id,
            capability_id=capability_id,
            provider=provider,
            request_hash=request_hash,
            execution_mode=execution_mode,
            business_id=business_id,
            project_id=project_id,
            chat_id=chat_id,
            approval_reference=approval_reference,
            mission_id=mission_id,
            commitment_id=commitment_id,
            schema_version=3 if lineage_requested else 2,
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
                            request_hash, execution_mode, state, business_id, project_id,
                            mission_id, commitment_id, chat_id, approval_reference,
                            dispatch_count, receipt_execution_id, last_error_class,
                            last_error_message, created_at, updated_at, schema_version, record_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self._intent_values(intent),
                    )
                return intent
            except sqlite3.IntegrityError as exc:
                raise ReceiptStoreConflictError(
                    f"EXECUTION_INTENT_ALREADY_EXISTS: intent_id={intent.intent_id}"
                ) from exc
            except sqlite3.Error as exc:
                raise _core._sqlite_failure("PREPARE_INTENT", exc) from exc

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
                request_hash=?, execution_mode=?, state=?, business_id=?, project_id=?,
                mission_id=?, commitment_id=?, chat_id=?, approval_reference=?,
                dispatch_count=?, receipt_execution_id=?, last_error_class=?,
                last_error_message=?, created_at=?, updated_at=?, schema_version=?, record_hash=?
            WHERE intent_id=?
            """,
            (
                normalized.request_id,
                normalized.run_id,
                normalized.agent_id,
                normalized.capability_id,
                normalized.provider,
                normalized.request_hash,
                normalized.execution_mode.value if normalized.execution_mode is not None else None,
                normalized.state.value,
                normalized.business_id,
                normalized.project_id,
                normalized.mission_id,
                normalized.commitment_id,
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


# Core helper functions resolve these globals at runtime. Point them at the
# Mission-aware models/binding while retaining the already-qualified algorithms.
_core.ExecutionReceipt = ExecutionReceipt
_core.ExecutionIntent = ExecutionIntent
_core._receipt_matches_intent_binding = _receipt_matches_intent_binding

# Preserve selected private compatibility entrypoints used by older tests/code.
_receipt_from_payload = _core._receipt_from_payload
_normalize_receipt = _core._normalize_receipt
_payload_hash = _core._payload_hash
_canonical_json = _core._canonical_json
_safe_approval_reference = _core._safe_approval_reference
_sqlite_failure = _core._sqlite_failure
