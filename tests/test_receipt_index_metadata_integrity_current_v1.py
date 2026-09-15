"""Adversarial regression for durable receipt index/payload integrity.

RISK-01: SQLite index metadata must be cryptographically bound to the hashed
receipt payload. Tampering run_id/agent_id/capability_id/status while leaving
payload_json + payload_hash untouched must fail closed.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools.receipts import (
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
    ReceiptStoreIntegrityError,
)


class ReceiptIndexMetadataIntegrityCurrentV1Tests(unittest.TestCase):
    @staticmethod
    def _receipt() -> ExecutionReceipt:
        return ExecutionReceipt(
            execution_id="EXEC-INDEX-INTEGRITY-001",
            run_id="RUN-INDEX-INTEGRITY-001",
            agent_id="intelligence",
            capability_id="web_search",
            provider="search_adapter",
            request_hash="req-hash-index-integrity-001",
            status=ExecutionStatus.SUCCESS,
            execution_mode=ExecutionMode.REAL,
            data={"ok": True},
        )

    def test_sqlite_receipt_index_column_tamper_is_detected(self) -> None:
        tamper_cases = (
            ("run_id", "RUN-TAMPERED"),
            ("agent_id", "creative"),
            ("capability_id", "publish_social"),
            ("status", ExecutionStatus.ERROR.value),
        )
        for column, tampered_value in tamper_cases:
            with self.subTest(column=column):
                with tempfile.TemporaryDirectory() as tmp:
                    db_path = Path(tmp) / "index-tamper.sqlite3"
                    repo = ExecutionReceiptRepository(database_path=db_path)
                    saved = repo.save_receipt(self._receipt())
                    repo.close()

                    conn = sqlite3.connect(str(db_path))
                    conn.execute(
                        f"UPDATE execution_receipts SET {column}=? WHERE execution_id=?",
                        (tampered_value, saved.execution_id),
                    )
                    conn.commit()
                    conn.close()

                    tampered = ExecutionReceiptRepository(database_path=db_path)
                    with self.assertRaises(ReceiptStoreIntegrityError):
                        tampered.get_receipt(saved.execution_id)
                    tampered.close()


if __name__ == "__main__":
    unittest.main()
