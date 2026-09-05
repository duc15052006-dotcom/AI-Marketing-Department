from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from connectors.marketing.operations import (
    ProviderOperationIntegrityError,
    ProviderOperationRepository,
)


class ProviderOperationScopeFaultIsolationAdversarialV1Tests(unittest.TestCase):
    @staticmethod
    def _create(repo: ProviderOperationRepository, *, business_id: str, external_id: str):
        return repo.create(
            provider="tiktok",
            connector_id="tiktok_main",
            connection_id="conn_tiktok_main",
            capability_id="social_publishing",
            action="publish_video",
            external_operation_id=external_id,
            business_id=business_id,
            project_id="PROJ-1",
            brand_id="BRAND-1",
            provider_status="SUBMITTED",
        )

    @staticmethod
    def _corrupt_payload(database_path: Path, operation_id: str) -> None:
        conn = sqlite3.connect(str(database_path))
        try:
            conn.execute(
                "UPDATE provider_operations SET payload_json = ? WHERE operation_id = ?",
                ("{corrupt-json", operation_id),
            )
            conn.commit()
        finally:
            conn.close()

    def test_corrupt_other_scope_record_does_not_break_healthy_scope_listing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            database_path = Path(td) / "provider_ops.sqlite3"
            repo = ProviderOperationRepository(database_path)
            healthy = self._create(
                repo,
                business_id="BUS-A",
                external_id="v_pub_url~v2.scope-a",
            )
            poisoned = self._create(
                repo,
                business_id="BUS-B",
                external_id="v_pub_url~v2.scope-b",
            )
            repo.close()

            self._corrupt_payload(database_path, poisoned.operation_id)

            reopened = ProviderOperationRepository(database_path)
            try:
                try:
                    records = reopened.list_scope(
                        business_id="BUS-A",
                        project_id="PROJ-1",
                        brand_id="BRAND-1",
                    )
                except ProviderOperationIntegrityError as exc:
                    self.fail(
                        "cross-scope corruption leaked into BUS-A listing: " + str(exc)
                    )
                self.assertEqual(
                    [record.operation_id for record in records],
                    [healthy.operation_id],
                )
            finally:
                reopened.close()

    def test_corrupt_record_inside_requested_scope_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            database_path = Path(td) / "provider_ops.sqlite3"
            repo = ProviderOperationRepository(database_path)
            poisoned = self._create(
                repo,
                business_id="BUS-A",
                external_id="v_pub_url~v2.scope-a-corrupt",
            )
            repo.close()

            self._corrupt_payload(database_path, poisoned.operation_id)

            reopened = ProviderOperationRepository(database_path)
            try:
                with self.assertRaises(ProviderOperationIntegrityError):
                    reopened.list_scope(
                        business_id="BUS-A",
                        project_id="PROJ-1",
                        brand_id="BRAND-1",
                    )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
