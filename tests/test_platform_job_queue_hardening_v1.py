"""Platform Batch #7 regression tests for job-queue hardening.

These tests use a minimal runtime stub so queue integrity is validated without
invoking the five-agent model pipeline.
"""

from __future__ import annotations

import itertools
import time
import unittest
from types import SimpleNamespace
from typing import Optional

from runtime.context import RunIdAlreadyExistsError, RuntimeStatus
from runtime.queue import ResourceLimiter, RunManager, RunQueueStatus


class StubRuntime:
    """Small deterministic runtime authority used only by queue tests."""

    def __init__(self, *, execute_error: Optional[str] = None) -> None:
        self._counter = itertools.count(1)
        self._reserved = set()
        self._active_contexts = {}
        self.started = []
        self.cancelled = []
        self.execute_error = execute_error

    def is_reserved_run_id(self, run_id: str) -> bool:
        return run_id in self._reserved

    def reserve_run_id(self, custom_id: Optional[str] = None, trusted: bool = False) -> str:
        del trusted
        run_id = custom_id or f"RUN-STUB-{next(self._counter):04d}"
        if run_id in self._reserved:
            raise RunIdAlreadyExistsError(f"RUN_ID_ALREADY_EXISTS: {run_id}")
        self._reserved.add(run_id)
        return run_id

    def get_active_context(self, run_id: str):
        return self._active_contexts.get(run_id)

    def start_run(
        self,
        *,
        objective: str,
        business_id: str,
        project_id=None,
        chat_id=None,
        reserved_run_id: str,
    ):
        del objective, business_id, project_id, chat_id
        ctx = SimpleNamespace(status=RuntimeStatus.RUNNING)
        self._active_contexts[reserved_run_id] = ctx
        self.started.append(reserved_run_id)
        return ctx

    def execute_run(self, ctx):
        if self.execute_error:
            raise RuntimeError(self.execute_error)
        ctx.status = RuntimeStatus.COMPLETED
        return ctx, {"status": "COMPLETED"}, None

    def cancel_run(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        ctx = self._active_contexts.get(run_id)
        if ctx is not None:
            ctx.status = RuntimeStatus.CANCELLED
        return True


class TestPlatformJobQueueHardeningV1(unittest.TestCase):
    @staticmethod
    def _wait_for_status(manager: RunManager, run_id: str, status: RunQueueStatus, timeout: float = 2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            item = manager.get_run(run_id)
            if item is not None and item.status == status:
                return item
            time.sleep(0.01)
        item = manager.get_run(run_id)
        raise AssertionError(f"run {run_id} did not reach {status}; final={getattr(item, 'status', None)}")

    def test_duplicate_run_id_never_overwrites_existing_item(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=0, max_queue_size=4)
        first = manager.enqueue_run("original objective", run_id="RUN-DUPLICATE-001")

        with self.assertRaises(RunIdAlreadyExistsError):
            manager.enqueue_run("attacker replacement", run_id="RUN-DUPLICATE-001")

        stored = manager.get_run(first.run_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.objective, "original objective")
        self.assertEqual(len(manager.list_runs()), 1)
        manager.shutdown()

    def test_bounded_queue_rejects_overload_without_reserving_new_run(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=0, max_queue_size=1)
        manager.enqueue_run("first", run_id="RUN-QUEUE-001")
        reserved_before = set(runtime._reserved)

        with self.assertRaisesRegex(RuntimeError, "RUN_QUEUE_FULL"):
            manager.enqueue_run("second", run_id="RUN-QUEUE-002")

        self.assertEqual(runtime._reserved, reserved_before)
        self.assertNotIn("RUN-QUEUE-002", runtime._reserved)
        self.assertEqual(manager.get_queue_stats()["queue_size"], 1)
        manager.shutdown()

    def test_enqueue_after_shutdown_fails_closed(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=0)
        self.assertTrue(manager.shutdown())
        self.assertTrue(manager.is_shutdown)

        with self.assertRaisesRegex(RuntimeError, "RUN_MANAGER_SHUTDOWN"):
            manager.enqueue_run("late work")

    def test_shutdown_joins_idle_worker(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=1)
        self.assertTrue(manager.shutdown(wait=True, timeout_seconds=1.0))
        self.assertTrue(all(not worker.is_alive() for worker in manager._workers))
        self.assertFalse(manager.get_queue_stats()["accepting_runs"])

    def test_shutdown_marks_pending_runs_cancelled(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=0, max_queue_size=2)
        item = manager.enqueue_run("pending", run_id="RUN-PENDING-001")

        self.assertTrue(manager.shutdown(cancel_pending=True))
        self.assertEqual(item.status, RunQueueStatus.CANCELLED)
        self.assertEqual(item.error, "RUN_CANCELLED_ON_SHUTDOWN")
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(runtime.started, [])

    def test_cancel_queued_run_does_not_dispatch_runtime(self) -> None:
        runtime = StubRuntime()
        manager = RunManager(runtime, max_workers=0)
        item = manager.enqueue_run("cancel before start", run_id="RUN-CANCEL-001")

        self.assertTrue(manager.cancel_run(item.run_id))
        self.assertEqual(item.status, RunQueueStatus.CANCELLED)
        self.assertEqual(item.error, "RUN_CANCELLED")
        self.assertIsNotNone(item.completed_at)
        self.assertEqual(runtime.cancelled, [])
        manager.shutdown()

    def test_worker_error_is_sanitized_before_queue_state_exposure(self) -> None:
        raw_secret = "queue-secret-token-123456"
        raw_key = "unsafe-key-999999"
        runtime = StubRuntime(
            execute_error=f"Authorization: Bearer {raw_secret} api_key={raw_key}"
        )
        manager = RunManager(runtime, max_workers=1)
        item = manager.enqueue_run("fail safely", run_id="RUN-SECRET-001")

        failed = self._wait_for_status(manager, item.run_id, RunQueueStatus.FAILED)
        dumped = failed.model_dump()
        self.assertNotIn(raw_secret, failed.error or "")
        self.assertNotIn(raw_key, failed.error or "")
        self.assertNotIn(raw_secret, dumped["error"] or "")
        self.assertNotIn(raw_key, dumped["error"] or "")
        self.assertIn("[REDACTED", dumped["error"] or "")
        manager.shutdown()

    def test_unknown_provider_is_conservatively_tracked(self) -> None:
        limiter = ResourceLimiter(default_max_concurrent_calls=1)

        self.assertTrue(limiter.acquire_slot("dynamic_mcp_provider", timeout_seconds=0.05))
        self.assertFalse(limiter.acquire_slot("dynamic_mcp_provider", timeout_seconds=0.01))
        states = limiter.get_provider_states()
        self.assertIn("dynamic_mcp_provider", states)
        self.assertEqual(states["dynamic_mcp_provider"]["max_concurrent_calls"], 1)
        self.assertEqual(states["dynamic_mcp_provider"]["active_calls"], 1)

        limiter.release_slot("dynamic_mcp_provider")
        self.assertTrue(limiter.acquire_slot("dynamic_mcp_provider", timeout_seconds=0.05))
        limiter.release_slot("dynamic_mcp_provider")

    def test_provider_limit_configuration_is_validated(self) -> None:
        with self.assertRaisesRegex(ValueError, "INVALID_PROVIDER_LIMIT"):
            ResourceLimiter(default_max_concurrent_calls=0)

        limiter = ResourceLimiter(provider_limits={"custom": 2})
        self.assertEqual(limiter.get_provider_states()["custom"]["max_concurrent_calls"], 2)
        with self.assertRaisesRegex(ValueError, "INVALID_PROVIDER_LIMIT"):
            limiter.set_provider_limit("custom", 0)


if __name__ == "__main__":
    unittest.main()
