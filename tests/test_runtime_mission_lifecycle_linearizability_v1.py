"""Deterministic RED regressions for Mission authority linearizability.

The races here use explicit gates rather than stress timing.  The production
contract is one linearization domain for lifecycle transition, mark_ready,
authoritative-scope mutation, commitment binding writes, and authority snapshot
reads.  #215 remains separate: direct commitment_id rebinding is intentionally
still allowed by this slice, but must be serialized with the same lock.
"""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

import runtime.mission as mission_module
from runtime.mission import (
    CommitmentRecord,
    MissionCommitmentError,
    MissionRecord,
    MissionStatus,
    MissionTransitionError,
)


class MissionLifecycleLinearizabilityV1Tests(unittest.TestCase):
    _TIMEOUT = 3.0

    def _mission(
        self,
        *,
        status: MissionStatus = MissionStatus.CREATED,
        commitment_id: str | None = None,
        business_id: str = "BIZ-001",
    ) -> MissionRecord:
        return MissionRecord(
            mission_id="MISSION-LIN-001",
            objective="Enforce linearizable Mission authority",
            business_id=business_id,
            project_id="PROJECT-001",
            user_id="USER-001",
            status=status,
            commitment_id=commitment_id,
        )

    def _commitment(self, commitment_id: str) -> CommitmentRecord:
        return CommitmentRecord(
            commitment_id=commitment_id,
            mission_id="MISSION-LIN-001",
            business_id="BIZ-001",
            project_id="PROJECT-001",
            user_id="USER-001",
            authority_mode="bounded",
        )

    def _start(self, target):
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread

    def _join(self, thread: threading.Thread) -> None:
        thread.join(self._TIMEOUT)
        self.assertFalse(thread.is_alive(), "deterministic race thread deadlocked")

    def test_terminal_transition_cannot_be_overwritten_by_stale_writer(self):
        mission = self._mission(
            status=MissionStatus.ACTIVE,
            commitment_id="COMMIT-001",
        )
        original_policy = mission_module._MISSION_TRANSITION_PAIRS
        terminal_checked = threading.Event()
        release_terminal = threading.Event()
        stale_checked = threading.Event()
        release_stale = threading.Event()
        results: list[tuple[str, str]] = []
        results_lock = threading.Lock()

        class _GatedPolicy:
            def __contains__(self, pair):
                if pair == (MissionStatus.ACTIVE, MissionStatus.COMPLETED):
                    terminal_checked.set()
                    if not release_terminal.wait(self_outer._TIMEOUT):
                        raise RuntimeError("terminal gate timeout")
                elif pair == (MissionStatus.ACTIVE, MissionStatus.WAITING_FOR_TIME):
                    stale_checked.set()
                    if not release_stale.wait(self_outer._TIMEOUT):
                        raise RuntimeError("stale gate timeout")
                return pair in original_policy

        self_outer = self

        def run(label: str, target: MissionStatus) -> None:
            try:
                mission.transition_to(target)
            except Exception as exc:  # exact class asserted below
                with results_lock:
                    results.append((label, type(exc).__name__))
            else:
                with results_lock:
                    results.append((label, "OK"))

        with patch.object(mission_module, "_MISSION_TRANSITION_PAIRS", _GatedPolicy()):
            terminal = self._start(lambda: run("terminal", MissionStatus.COMPLETED))
            self.assertTrue(terminal_checked.wait(self._TIMEOUT))

            stale = self._start(lambda: run("stale", MissionStatus.WAITING_FOR_TIME))
            # Pre-fix the stale writer enters the policy with an ACTIVE snapshot.
            # Post-fix it blocks on the authority lock until terminal commits.
            stale_checked.wait(0.75)

            release_terminal.set()
            self._join(terminal)
            release_stale.set()
            self._join(stale)

        self.assertEqual(mission.status, MissionStatus.COMPLETED)
        self.assertIn(("terminal", "OK"), results)
        self.assertIn(("stale", "MissionTransitionError"), results)
        self.assertEqual(len(results), 2)

    def test_concurrent_mark_ready_has_exactly_one_winner(self):
        mission = self._mission()
        c1 = self._commitment("COMMIT-001")
        c2 = self._commitment("COMMIT-002")
        original_validate = MissionRecord._validate_executable_commitment
        first_entered = threading.Event()
        second_entered = threading.Event()
        release = threading.Event()
        entry_lock = threading.Lock()
        entry_count = 0
        results: list[tuple[str, str]] = []
        results_lock = threading.Lock()

        def gated_validate(record, commitment, *, now=None):
            nonlocal entry_count
            validated = original_validate(record, commitment, now=now)
            with entry_lock:
                entry_count += 1
                if entry_count == 1:
                    first_entered.set()
                elif entry_count == 2:
                    second_entered.set()
            if not release.wait(self._TIMEOUT):
                raise RuntimeError("mark_ready gate timeout")
            return validated

        def run(commitment: CommitmentRecord) -> None:
            try:
                mission.mark_ready(commitment)
            except Exception as exc:
                with results_lock:
                    results.append((commitment.commitment_id, type(exc).__name__))
            else:
                with results_lock:
                    results.append((commitment.commitment_id, "OK"))

        with patch.object(MissionRecord, "_validate_executable_commitment", gated_validate):
            t1 = self._start(lambda: run(c1))
            self.assertTrue(first_entered.wait(self._TIMEOUT))
            t2 = self._start(lambda: run(c2))
            second_entered.wait(0.75)
            release.set()
            self._join(t1)
            self._join(t2)

        winners = [cid for cid, outcome in results if outcome == "OK"]
        losers = [outcome for _, outcome in results if outcome != "OK"]
        self.assertEqual(len(winners), 1, results)
        self.assertEqual(losers, ["MissionCommitmentError"], results)
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.commitment_id, winners[0])

    def test_mark_ready_and_scope_mutation_cannot_create_torn_authority(self):
        mission = self._mission()
        commitment = self._commitment("COMMIT-001")
        original_validate = MissionRecord._validate_executable_commitment
        validated = threading.Event()
        release_ready = threading.Event()
        mutation_done = threading.Event()
        ready_result: list[str] = []
        mutation_result: list[str] = []

        def gated_validate(record, candidate, *, now=None):
            result = original_validate(record, candidate, now=now)
            validated.set()
            if not release_ready.wait(self._TIMEOUT):
                raise RuntimeError("scope race gate timeout")
            return result

        def run_ready() -> None:
            try:
                mission.mark_ready(commitment)
            except Exception as exc:
                ready_result.append(type(exc).__name__)
            else:
                ready_result.append("OK")

        def mutate_scope() -> None:
            try:
                mission.business_id = "BIZ-OTHER"
            except Exception as exc:
                mutation_result.append(type(exc).__name__)
            else:
                mutation_result.append("OK")
            finally:
                mutation_done.set()

        with patch.object(MissionRecord, "_validate_executable_commitment", gated_validate):
            ready_thread = self._start(run_ready)
            self.assertTrue(validated.wait(self._TIMEOUT))
            mutation_thread = self._start(mutate_scope)
            mutation_done.wait(0.75)
            release_ready.set()
            self._join(ready_thread)
            self._join(mutation_thread)

        self.assertEqual(ready_result, ["OK"])
        self.assertEqual(mutation_result, ["MissionTransitionError"])
        self.assertEqual(mission.status, MissionStatus.READY)
        self.assertEqual(mission.business_id, commitment.business_id)
        self.assertEqual(mission.commitment_id, commitment.commitment_id)

    def test_model_dump_authority_snapshot_is_atomic_with_mark_ready(self):
        mission = self._mission()
        commitment = self._commitment("COMMIT-001")
        original_serialize = MissionRecord._serialize_val
        status_serialized = threading.Event()
        release_dump = threading.Event()
        ready_done = threading.Event()
        dump_result: list[dict] = []
        ready_result: list[str] = []
        gate_once = threading.Event()

        def gated_serialize(record, value):
            serialized = original_serialize(record, value)
            if value == MissionStatus.CREATED and not gate_once.is_set():
                gate_once.set()
                status_serialized.set()
                if not release_dump.wait(self._TIMEOUT):
                    raise RuntimeError("model_dump gate timeout")
            return serialized

        def run_dump() -> None:
            dump_result.append(mission.model_dump())

        def run_ready() -> None:
            try:
                mission.mark_ready(commitment)
            except Exception as exc:
                ready_result.append(type(exc).__name__)
            else:
                ready_result.append("OK")
            finally:
                ready_done.set()

        with patch.object(MissionRecord, "_serialize_val", gated_serialize):
            dump_thread = self._start(run_dump)
            self.assertTrue(status_serialized.wait(self._TIMEOUT))
            ready_thread = self._start(run_ready)
            ready_done.wait(0.75)
            release_dump.set()
            self._join(dump_thread)
            self._join(ready_thread)

        self.assertEqual(ready_result, ["OK"])
        self.assertEqual(len(dump_result), 1)
        snapshot = dump_result[0]
        self.assertIn(
            (snapshot["status"], snapshot["commitment_id"]),
            {
                (MissionStatus.CREATED.value, None),
                (MissionStatus.READY.value, commitment.commitment_id),
            },
        )

    def test_lock_selector_is_bounded_and_all_64_stripes_are_reachable(self):
        missions = [
            MissionRecord(
                mission_id=f"MISSION-SPREAD-{index:04d}",
                objective="Measure authority lock distribution",
                business_id="BIZ-001",
                project_id="PROJECT-001",
                user_id="USER-001",
            )
            for index in range(256)
        ]
        live_indexes = {
            mission_module._mission_authority_lock_index(mission)
            for mission in missions
        }
        self.assertTrue(live_indexes)
        self.assertTrue(all(0 <= index < 64 for index in live_indexes))

        synthetic_indexes = set()
        sentinel = object()
        for identity in range(64):
            with patch.object(mission_module, "id", return_value=identity, create=True):
                synthetic_indexes.add(
                    mission_module._mission_authority_lock_index(sentinel)
                )
        self.assertEqual(synthetic_indexes, set(range(64)))

    def test_authority_lock_releases_after_exception(self):
        mission = self._mission(
            status=MissionStatus.ACTIVE,
            commitment_id="COMMIT-001",
        )
        # The helper itself is part of the runtime contract and must not be stored
        # on the MissionRecord (which would affect serialization/copy semantics).
        lock = mission_module._mission_authority_lock(mission)
        self.assertIsNotNone(lock)
        self.assertFalse(any("lock" in key.lower() for key in mission.__dict__))

        with self.assertRaisesRegex(
            MissionTransitionError,
            "MISSION_READY_REQUIRES_COMMITMENT_VALIDATION",
        ):
            mission.transition_to(MissionStatus.READY)

        result: list[str] = []

        def valid_transition() -> None:
            try:
                mission.transition_to(MissionStatus.WAITING_FOR_TIME)
            except Exception as exc:
                result.append(type(exc).__name__)
            else:
                result.append("OK")

        thread = self._start(valid_transition)
        self._join(thread)
        self.assertEqual(result, ["OK"])
        self.assertEqual(mission.status, MissionStatus.WAITING_FOR_TIME)

    def test_commitment_id_rebinding_remains_separate_215_control(self):
        mission = self._mission(
            status=MissionStatus.READY,
            commitment_id="COMMIT-001",
        )
        mission.commitment_id = "COMMIT-002"
        self.assertEqual(mission.commitment_id, "COMMIT-002")


if __name__ == "__main__":
    unittest.main()
