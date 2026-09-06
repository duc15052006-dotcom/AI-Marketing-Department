from __future__ import annotations

import threading
import unittest

from runtime.lineage import LineageInspector
from tools.receipts import ExecutionReceipt


class _CoordinatedDict(dict):
    """Force a writer to mutate while a values() iterator is live."""

    def __init__(self, initial: dict, reader_inside: threading.Event, writer_committed: threading.Event) -> None:
        super().__init__(initial)
        self.reader_inside = reader_inside
        self.writer_committed = writer_committed

    def values(self):
        iterator = super().values()
        first = True
        for value in iterator:
            if first:
                first = False
                self.reader_inside.set()
                # With the production lock, add_receipt cannot commit until
                # get_all_receipts has finished iterating and released it.
                self.writer_committed.wait(timeout=0.5)
            yield value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.reader_inside.is_set():
            self.writer_committed.set()


def _receipt(execution_id: str) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=execution_id,
        run_id="RUN-LINEAGE-CONCURRENCY",
        agent_id="intelligence",
        capability_id="web_search",
        provider="test",
        request_hash=f"hash-{execution_id}",
    )


class LineageInspectorConcurrencyV1Tests(unittest.TestCase):
    def test_get_all_receipts_is_atomic_against_concurrent_add(self) -> None:
        inspector = LineageInspector(receipts=[_receipt("EXEC-SEED-1"), _receipt("EXEC-SEED-2")])
        reader_inside = threading.Event()
        writer_committed = threading.Event()
        inspector._receipts_by_id = _CoordinatedDict(
            dict(inspector._receipts_by_id),
            reader_inside,
            writer_committed,
        )

        writer_error = []

        def writer() -> None:
            self.assertTrue(reader_inside.wait(timeout=2.0))
            try:
                inspector.add_receipt(_receipt("EXEC-CONCURRENT"))
            except BaseException as exc:
                writer_error.append(exc)

        thread = threading.Thread(target=writer, name="lineage-writer")
        thread.start()

        read_error = None
        receipts = []
        try:
            receipts = inspector.get_all_receipts()
        except RuntimeError as exc:
            read_error = exc

        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "writer thread must terminate")
        self.assertEqual(writer_error, [])
        self.assertIsNone(
            read_error,
            f"lineage receipt iteration raced with add_receipt: {read_error}",
        )
        self.assertGreaterEqual(len(receipts), 2)
        self.assertIn("EXEC-CONCURRENT", {r.execution_id for r in inspector.get_all_receipts()})


if __name__ == "__main__":
    unittest.main()
