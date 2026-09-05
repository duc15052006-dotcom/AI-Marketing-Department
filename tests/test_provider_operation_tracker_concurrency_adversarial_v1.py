from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path

from connectors.marketing.operations import (
    ProviderOperationConflictError,
    ProviderOperationRepository,
    ProviderOperationState,
)


class _SecondReadBarrierRepository(ProviderOperationRepository):
    """Force two repository instances to validate the same stale record hash."""

    def __init__(self, database_path: Path, barrier: threading.Barrier) -> None:
        super().__init__(database_path)
        self._second_read_barrier = barrier
        self._get_calls = 0

    def get(self, operation_id: str):
        record = super().get(operation_id)
        self._get_calls += 1
        if self._get_calls == 2:
            self._second_read_barrier.wait(timeout=5)
        return record


class ProviderOperationCrossInstanceConcurrencyAdversarialV1Tests(unittest.TestCase):
    def test_only_one_cross_instance_terminal_update_can_commit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            database_path = Path(td) / "provider_ops.sqlite3"
            barrier = threading.Barrier(2)
            repo_a = _SecondReadBarrierRepository(database_path, barrier)
            record = repo_a.create(
                provider="tiktok",
                connector_id="tiktok_main",
                connection_id="conn_tiktok_main",
                capability_id="social_publishing",
                action="publish_video",
                external_operation_id="v_pub_url~v2.concurrent-terminal",
                business_id="BUS-1",
                project_id="PROJ-1",
                brand_id="BRAND-1",
                provider_status="PROCESSING_UPLOAD",
            )
            repo_a.record_status(
                record.operation_id,
                state=ProviderOperationState.PROCESSING,
                provider_status="PROCESSING_UPLOAD",
            )
            # Reset the call counter because the setup transition performs two reads.
            repo_a._get_calls = 0
            repo_b = _SecondReadBarrierRepository(database_path, barrier)

            errors: list[BaseException] = []

            def finalize(repo: ProviderOperationRepository, state: ProviderOperationState, status: str) -> None:
                try:
                    repo.record_status(
                        record.operation_id,
                        state=state,
                        provider_status=status,
                    )
                except BaseException as exc:  # capture the worker result for the assertion below
                    errors.append(exc)

            succeeded = threading.Thread(
                target=finalize,
                args=(repo_a, ProviderOperationState.SUCCEEDED, "PUBLISH_COMPLETE"),
            )
            failed = threading.Thread(
                target=finalize,
                args=(repo_b, ProviderOperationState.FAILED, "FAILED"),
            )
            succeeded.start()
            failed.start()
            succeeded.join(timeout=10)
            failed.join(timeout=10)

            self.assertFalse(succeeded.is_alive())
            self.assertFalse(failed.is_alive())
            self.assertEqual(len(errors), 1, errors)
            self.assertIsInstance(errors[0], ProviderOperationConflictError)
            self.assertTrue(repo_a.get(record.operation_id).state.terminal)

            repo_a.close()
            repo_b.close()


if __name__ == "__main__":
    unittest.main()
