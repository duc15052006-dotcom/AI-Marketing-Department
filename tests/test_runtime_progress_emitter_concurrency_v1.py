from __future__ import annotations

import threading
import unittest

from runtime.progress import ProgressEmitter, ProgressEventType


class _BlockingMetadata:
    """Pause dict(metadata) after emit has reserved its sequence number."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __iter__(self):
        self.entered.set()
        if not self.release.wait(timeout=3.0):
            raise RuntimeError("blocking metadata was not released")
        yield ("source", "worker-a")


class RuntimeProgressEmitterConcurrencyV1Tests(unittest.TestCase):
    def test_concurrent_emits_preserve_history_sequence_order(self) -> None:
        emitter = ProgressEmitter(run_id="RUN-PROGRESS-RACE")
        blocking_metadata = _BlockingMetadata()
        errors: list[BaseException] = []

        def emit_first() -> None:
            try:
                emitter.emit(
                    ProgressEventType.MODEL_STARTED,
                    metadata=blocking_metadata,  # type: ignore[arg-type]
                )
            except BaseException as exc:
                errors.append(exc)

        first = threading.Thread(target=emit_first, name="progress-worker-a")
        first.start()
        self.assertTrue(
            blocking_metadata.entered.wait(timeout=2.0),
            "first emit must pause after reserving sequence 1",
        )

        # Pre-fix, the first worker has already incremented _sequence to 1 but
        # has not appended its event. A second worker can reserve sequence 2 and
        # append first, producing history [2, 1]. A synchronized emitter must
        # serialize this critical section and preserve history order [1, 2].
        second_done = threading.Event()

        def emit_second() -> None:
            try:
                emitter.emit(ProgressEventType.MODEL_COMPLETED)
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()

        second = threading.Thread(target=emit_second, name="progress-worker-b")
        second.start()

        # Give worker B a deterministic opportunity to reach the same critical
        # section before worker A is released.
        second_done.wait(timeout=0.25)
        blocking_metadata.release.set()

        first.join(timeout=3.0)
        second.join(timeout=3.0)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])

        sequences = [event.sequence for event in emitter.events]
        self.assertEqual(
            sequences,
            [1, 2],
            "per-run progress history must remain strictly monotonic under concurrent emits",
        )
        self.assertEqual(emitter.current_sequence, 2)

    def test_finalize_is_linearizable_with_inflight_emit(self) -> None:
        emitter = ProgressEmitter(run_id="RUN-PROGRESS-FINALIZE-RACE")
        blocking_metadata = _BlockingMetadata()
        emit_errors: list[BaseException] = []

        def emit_inflight() -> None:
            try:
                emitter.emit(
                    ProgressEventType.MODEL_STARTED,
                    metadata=blocking_metadata,  # type: ignore[arg-type]
                )
            except BaseException as exc:
                emit_errors.append(exc)

        emit_thread = threading.Thread(target=emit_inflight, name="progress-inflight")
        emit_thread.start()
        self.assertTrue(
            blocking_metadata.entered.wait(timeout=2.0),
            "emit must be in-flight before finalize starts",
        )

        finalize_returned = threading.Event()

        def finalize() -> None:
            emitter.finalize()
            finalize_returned.set()

        finalize_thread = threading.Thread(target=finalize, name="progress-finalizer")
        finalize_thread.start()

        # A linearizable finalizer cannot return while an earlier emit is still
        # between sequence reservation and event commit; otherwise that emit can
        # mutate history after finalize() has already returned.
        self.assertFalse(
            finalize_returned.wait(timeout=0.15),
            "finalize returned while an earlier emit was still uncommitted",
        )

        blocking_metadata.release.set()
        emit_thread.join(timeout=3.0)
        finalize_thread.join(timeout=3.0)
        self.assertFalse(emit_thread.is_alive())
        self.assertFalse(finalize_thread.is_alive())
        self.assertEqual(emit_errors, [])
        self.assertTrue(emitter.is_closed)
        self.assertEqual(emitter.current_sequence, 1)
        self.assertEqual([event.sequence for event in emitter.events], [1])


if __name__ == "__main__":
    unittest.main()
