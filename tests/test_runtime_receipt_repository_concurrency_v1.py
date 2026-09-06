from __future__ import annotations

import threading
import unittest

from tools.receipts import ExecutionReceipt, ExecutionReceiptRepository


class _CoordinatedDict(dict):
    """Force a writer through the repository while a values() iterator is live."""

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
                # On the fixed implementation, repository locking prevents the
                # writer from reaching __setitem__ until this reader finishes.
                self.writer_committed.wait(timeout=0.5)
            yield value

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.reader_inside.is_set():
            self.writer_committed.set()


def _receipt(execution_id: str) -> ExecutionReceipt:
    return ExecutionReceipt(
        execution_id=execution_id,
        run_id="RUN-CONCURRENCY",
        agent_id="intelligence",
        capability_id="web_search",
        provider="test",
        request_hash=f"hash-{execution_id}",
    )


class ExecutionReceiptRepositoryConcurrencyV1Tests(unittest.TestCase):
    def test_list_receipts_for_run_is_atomic_against_concurrent_save(self) -> None:
        repo = ExecutionReceiptRepository()
        repo.save_receipt(_receipt("EXEC-SEED-1"))
        repo.save_receipt(_receipt("EXEC-SEED-2"))

        reader_inside = threading.Event()
        writer_committed = threading.Event()
        repo._receipts = _CoordinatedDict(dict(repo._receipts), reader_inside, writer_committed)

        writer_error = []

        def writer() -> None:
            self.assertTrue(reader_inside.wait(timeout=2.0))
            try:
                repo.save_receipt(_receipt("EXEC-CONCURRENT"))
            except BaseException as exc:  # surfaced after join
                writer_error.append(exc)

        thread = threading.Thread(target=writer, name="receipt-writer")
        thread.start()

        read_error = None
        listed = []
        try:
            listed = repo.list_receipts_for_run("RUN-CONCURRENCY")
        except RuntimeError as exc:
            read_error = exc

        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive(), "writer thread must terminate")
        self.assertEqual(writer_error, [])
        self.assertIsNone(
            read_error,
            f"receipt iteration raced with save_receipt: {read_error}",
        )
        self.assertGreaterEqual(len(listed), 2)
        self.assertIsNotNone(repo.get_receipt("EXEC-CONCURRENT"))


if __name__ == "__main__":
    unittest.main()
