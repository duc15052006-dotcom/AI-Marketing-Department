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
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

from schemas.base import Field
from tools import receipts_core as _core
from tools.receipts_core import *  # noqa: F401,F403 - preserve the established module surface


_BaseExecutionReceipt = _core.ExecutionReceipt
_BaseExecutionIntent = _core.ExecutionIntent
_BaseExecutionReceiptRepository = _core.ExecutionReceiptRepository
_base_receipt_matches_intent_binding = _core._receipt_matches_intent_binding


class MissionReconciliationResolution(str, Enum):
    """Evidence-backed terminal classifications for an ambiguous external effect."""

    CONFIRMED_EXTERNAL_ACTION_APPLIED = "CONFIRMED_EXTERNAL_ACTION_APPLIED"
    CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED = "CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED"


# Preserve the established ReconciliationOutcome enum object used by legacy callers
# while exposing the two Phase-4 evidence-resolution outcomes on that public surface.
ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_APPLIED = (  # type: ignore[attr-defined]
    MissionReconciliationResolution.CONFIRMED_EXTERNAL_ACTION_APPLIED
)
ReconciliationOutcome.CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED = (  # type: ignore[attr-defined]
    MissionReconciliationResolution.CONFIRMED_EXTERNAL_ACTION_NOT_APPLIED
)


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


@dataclass(frozen=True)
class ExecutionReconciliationRecord:
    """Immutable evidence that resolves one already-ambiguous Mission effect."""

    reconciliation_id: str
    intent_id: str
    outcome: MissionReconciliationResolution
    evidence_hash: str
    evidence_source: str
    business_id: str
    project_id: str
    mission_id: str
    commitment_id: str
    created_at: str = ""
    record_hash: str = ""

    def normalized(self) -> "ExecutionReconciliationRecord":
        required = {
            "reconciliation_id": self.reconciliation_id,
            "intent_id": self.intent_id,
            "evidence_hash": self.evidence_hash,
            "evidence_source": self.evidence_source,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "mission_id": self.mission_id,
            "commitment_id": self.commitment_id,
        }
        normalized_strings: Dict[str, str] = {}
        for name, value in required.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name.upper()}_REQUIRED: reconciliation {name} is required"
                )
            normalized_strings[name] = value.strip()

        evidence_hash = normalized_strings["evidence_hash"].lower()
        if len(evidence_hash) != 64 or any(ch not in "0123456789abcdef" for ch in evidence_hash):
            raise ValueError(
                "INVALID_RECONCILIATION_EVIDENCE_HASH: evidence_hash must be SHA-256 hex"
            )
        evidence_source = _core.sanitize_sensitive_text(
            normalized_strings["evidence_source"]
        ).strip()
        if not evidence_source:
            raise ValueError(
                "EVIDENCE_SOURCE_REQUIRED: reconciliation evidence_source is required"
            )

        outcome = self.outcome
        if not isinstance(outcome, MissionReconciliationResolution):
            raw_outcome = outcome.value if isinstance(outcome, Enum) else str(outcome)
            outcome = MissionReconciliationResolution(raw_outcome)

        created_at = self.created_at or _core._utc_now_iso()
        normalized = replace(
            self,
            reconciliation_id=normalized_strings["reconciliation_id"],
            intent_id=normalized_strings["intent_id"],
            outcome=outcome,
            evidence_hash=evidence_hash,
            evidence_source=evidence_source,
            business_id=normalized_strings["business_id"],
            project_id=normalized_strings["project_id"],
            mission_id=normalized_strings["mission_id"],
            commitment_id=normalized_strings["commitment_id"],
            created_at=created_at,
            record_hash="",
        )
        return replace(normalized, record_hash=normalized.calculate_hash())

    def hash_payload(self) -> Dict[str, Any]:
        return {
            "reconciliation_id": self.reconciliation_id,
            "intent_id": self.intent_id,
            "outcome": self.outcome.value,
            "evidence_hash": self.evidence_hash,
            "evidence_source": self.evidence_source,
            "business_id": self.business_id,
            "project_id": self.project_id,
            "mission_id": self.mission_id,
            "commitment_id": self.commitment_id,
            "created_at": self.created_at,
        }

    def calculate_hash(self) -> str:
        return _core._payload_hash(self.hash_payload())

    def verify_integrity(self) -> bool:
        return bool(self.record_hash) and self.record_hash == self.calculate_hash()


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


def _same_reconciliation_resolution(
    left: ExecutionReconciliationRecord,
    right: ExecutionReconciliationRecord,
) -> bool:
    """Compare immutable decision/evidence semantics, excluding generated identity/time."""

    return (
        left.intent_id == right.intent_id
        and left.outcome == right.outcome
        and left.evidence_hash == right.evidence_hash
        and left.evidence_source == right.evidence_source
        and left.business_id == right.business_id
        and left.project_id == right.project_id
        and left.mission_id == right.mission_id
        and left.commitment_id == right.commitment_id
    )


class ExecutionReceiptRepository(_BaseExecutionReceiptRepository):
    """Durable receipt journal extended with Mission lineage and reconciliation evidence."""

    def __init__(self, database_path: Optional[str | Path] = None) -> None:
        self._reconciliations: Dict[str, ExecutionReconciliationRecord] = {}
        super().__init__(database_path=database_path)

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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_reconciliations (
                    intent_id TEXT PRIMARY KEY,
                    reconciliation_id TEXT NOT NULL UNIQUE,
                    outcome TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    evidence_source TEXT NOT NULL,
                    business_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    mission_id TEXT NOT NULL,
                    commitment_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    FOREIGN KEY(intent_id) REFERENCES execution_intents(intent_id)
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_execution_reconciliations_outcome "
                "ON execution_reconciliations(outcome, intent_id)"
            )

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

    @staticmethod
    def _reconciliation_from_row(row: sqlite3.Row) -> ExecutionReconciliationRecord:
        record = ExecutionReconciliationRecord(
            reconciliation_id=row["reconciliation_id"],
            intent_id=row["intent_id"],
            outcome=MissionReconciliationResolution(row["outcome"]),
            evidence_hash=row["evidence_hash"],
            evidence_source=row["evidence_source"],
            business_id=row["business_id"],
            project_id=row["project_id"],
            mission_id=row["mission_id"],
            commitment_id=row["commitment_id"],
            created_at=row["created_at"],
            record_hash=row["record_hash"],
        )
        if not record.verify_integrity():
            raise ReceiptStoreIntegrityError(
                "EXECUTION_RECONCILIATION_INTEGRITY_MISMATCH: "
                f"intent_id={record.intent_id}"
            )
        return record

    def get_execution_reconciliation(
        self,
        intent_id: str,
    ) -> Optional[ExecutionReconciliationRecord]:
        """Read immutable evidence resolution for an ambiguous execution intent."""

        self._ensure_open()
        with self._lock:
            if self._conn is None:
                record = self._reconciliations.get(intent_id)
                return copy.deepcopy(record) if record is not None else None
            try:
                row = self._conn.execute(
                    "SELECT * FROM execution_reconciliations WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
            except sqlite3.Error as exc:
                raise _core._sqlite_failure("GET_RECONCILIATION", exc) from exc
            return self._reconciliation_from_row(row) if row is not None else None

    def record_execution_reconciliation(
        self,
        intent_id: str,
        *,
        outcome: MissionReconciliationResolution,
        evidence_hash: str,
        evidence_source: str,
        business_id: str,
        project_id: str,
        mission_id: str,
        commitment_id: str,
    ) -> ExecutionReconciliationRecord:
        """Immutably resolve AMBIGUOUS evidence without replaying the external action."""

        self._ensure_open()
        with self._lock:
            current = self.get_execution_intent(intent_id)
            if current is None:
                raise ReceiptStoreConflictError(
                    f"EXECUTION_INTENT_NOT_FOUND: intent_id={intent_id}"
                )
            if current.state != ExecutionIntentState.AMBIGUOUS:
                raise ReceiptStoreConflictError(
                    "EXECUTION_RECONCILIATION_REQUIRES_AMBIGUOUS_INTENT: "
                    f"intent_id={intent_id} state={current.state.value}"
                )
            if current.schema_version < 3:
                raise ReceiptStoreIntegrityError(
                    "EXECUTION_RECONCILIATION_MISSION_AUTHORITY_UNBOUND: "
                    f"intent_id={intent_id}"
                )

            authority = {
                "business_id": current.business_id,
                "project_id": current.project_id,
                "mission_id": current.mission_id,
                "commitment_id": current.commitment_id,
            }
            supplied = {
                "business_id": business_id,
                "project_id": project_id,
                "mission_id": mission_id,
                "commitment_id": commitment_id,
            }
            for name, expected in authority.items():
                candidate = supplied[name]
                if not isinstance(expected, str) or not expected.strip():
                    raise ReceiptStoreIntegrityError(
                        "EXECUTION_RECONCILIATION_AUTHORITY_UNBOUND: "
                        f"intent_id={intent_id} field={name}"
                    )
                if not isinstance(candidate, str) or candidate.strip() != expected:
                    raise ReceiptStoreIntegrityError(
                        "EXECUTION_RECONCILIATION_AUTHORITY_MISMATCH: "
                        f"intent_id={intent_id} field={name}"
                    )

            candidate = ExecutionReconciliationRecord(
                reconciliation_id=f"RECON-{uuid.uuid4().hex[:16].upper()}",
                intent_id=intent_id,
                outcome=outcome,
                evidence_hash=evidence_hash,
                evidence_source=evidence_source,
                business_id=business_id,
                project_id=project_id,
                mission_id=mission_id,
                commitment_id=commitment_id,
            ).normalized()

            existing = self.get_execution_reconciliation(intent_id)
            if existing is not None:
                if _same_reconciliation_resolution(existing, candidate):
                    return existing
                raise ReceiptStoreConflictError(
                    "EXECUTION_RECONCILIATION_IMMUTABLE_CONFLICT: "
                    f"intent_id={intent_id}"
                )

            if self._conn is None:
                self._reconciliations[intent_id] = candidate
                return copy.deepcopy(candidate)

            try:
                with self._conn:
                    cur = self._conn.execute(
                        """
                        INSERT OR IGNORE INTO execution_reconciliations(
                            intent_id, reconciliation_id, outcome, evidence_hash,
                            evidence_source, business_id, project_id, mission_id,
                            commitment_id, created_at, record_hash
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate.intent_id,
                            candidate.reconciliation_id,
                            candidate.outcome.value,
                            candidate.evidence_hash,
                            candidate.evidence_source,
                            candidate.business_id,
                            candidate.project_id,
                            candidate.mission_id,
                            candidate.commitment_id,
                            candidate.created_at,
                            candidate.record_hash,
                        ),
                    )
                if cur.rowcount == 1:
                    return candidate
                raced = self.get_execution_reconciliation(intent_id)
                if raced is not None and _same_reconciliation_resolution(raced, candidate):
                    return raced
                raise ReceiptStoreConflictError(
                    "EXECUTION_RECONCILIATION_IMMUTABLE_CONFLICT: "
                    f"intent_id={intent_id}"
                )
            except ReceiptStoreError:
                raise
            except sqlite3.IntegrityError as exc:
                raise ReceiptStoreConflictError(
                    "EXECUTION_RECONCILIATION_INSERT_CONFLICT: "
                    f"intent_id={intent_id}"
                ) from exc
            except sqlite3.Error as exc:
                raise _core._sqlite_failure("SAVE_RECONCILIATION", exc) from exc

    def assess_execution_intent(self, intent_id: str) -> ReconciliationAssessment:
        """Overlay immutable reconciliation evidence on the established assessment."""

        base = super().assess_execution_intent(intent_id)
        intent = self.get_execution_intent(intent_id)
        if intent is None or intent.state != ExecutionIntentState.AMBIGUOUS:
            return base
        record = self.get_execution_reconciliation(intent_id)
        if record is None:
            return base
        if (
            record.business_id != intent.business_id
            or record.project_id != intent.project_id
            or record.mission_id != intent.mission_id
            or record.commitment_id != intent.commitment_id
        ):
            raise ReceiptStoreIntegrityError(
                "EXECUTION_RECONCILIATION_AUTHORITY_MISMATCH: "
                f"intent_id={intent_id}"
            )
        return ReconciliationAssessment(
            intent_id=intent_id,
            outcome=record.outcome,
            receipt_execution_id=intent.receipt_execution_id,
            reason=(
                "Ambiguous external effect resolved by immutable, Mission-bound "
                "reconciliation evidence; the original intent remains non-redispatchable."
            ),
        )


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
