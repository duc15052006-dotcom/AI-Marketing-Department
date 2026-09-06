from __future__ import annotations

import threading
import unittest

from runtime.dependency_scheduler import (
    AdaptiveTaskCompiler,
    DependencyAwareScheduler,
    RuntimeTaskSpec,
    ScheduleValidationError,
)


class DependencyAwareSchedulerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = DependencyAwareScheduler(max_workers=4)

    def test_independent_tasks_share_the_same_parallel_wave(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="market",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research.market"}),
            ),
            RuntimeTaskSpec(
                task_id="competitors",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research.competitors"}),
            ),
            RuntimeTaskSpec(
                task_id="customers",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research.customers"}),
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("market", "competitors", "customers"),))
        self.assertEqual(plan.mode, "ADAPTIVE_DAG")

    def test_explicit_dependency_forces_a_later_wave(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="research",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research"}),
            ),
            RuntimeTaskSpec(
                task_id="strategy",
                agent_id="strategist",
                depends_on=frozenset({"research"}),
                reads=frozenset({"research"}),
                writes=frozenset({"strategy"}),
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("research",), ("strategy",)))

    def test_write_conflict_is_serialized_even_without_declared_dependency(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="a",
                agent_id="creative",
                reads=frozenset({"objective"}),
                writes=frozenset({"shared.creative"}),
            ),
            RuntimeTaskSpec(
                task_id="b",
                agent_id="creative",
                reads=frozenset({"objective"}),
                writes=frozenset({"shared.creative"}),
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("a",), ("b",)))

    def test_read_write_conflict_is_serialized(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="writer",
                agent_id="intelligence",
                writes=frozenset({"research.market"}),
            ),
            RuntimeTaskSpec(
                task_id="reader",
                agent_id="strategist",
                reads=frozenset({"research.market"}),
                writes=frozenset({"strategy"}),
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("writer",), ("reader",)))

    def test_unknown_resource_scope_fails_closed_to_exclusive_wave(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="known",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research.known"}),
            ),
            RuntimeTaskSpec(
                task_id="unknown",
                agent_id="intelligence",
                resource_scope_known=False,
            ),
            RuntimeTaskSpec(
                task_id="later",
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({"research.later"}),
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("known",), ("unknown",), ("later",)))

    def test_side_effecting_task_is_never_co_scheduled(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="analysis",
                agent_id="performance",
                reads=frozenset({"objective"}),
                writes=frozenset({"analysis"}),
            ),
            RuntimeTaskSpec(
                task_id="publish",
                agent_id="creative",
                reads=frozenset({"analysis"}),
                writes=frozenset({"external.channel"}),
                side_effecting=True,
            ),
        ]

        plan = self.scheduler.plan(tasks)

        self.assertEqual(plan.waves, (("analysis",), ("publish",)))

    def test_duplicate_task_id_is_rejected(self) -> None:
        tasks = [
            RuntimeTaskSpec(task_id="same", agent_id="intelligence"),
            RuntimeTaskSpec(task_id="same", agent_id="strategist"),
        ]
        with self.assertRaisesRegex(ScheduleValidationError, "DUPLICATE_TASK_ID"):
            self.scheduler.plan(tasks)

    def test_unknown_dependency_is_rejected(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="strategy",
                agent_id="strategist",
                depends_on=frozenset({"missing-research"}),
            )
        ]
        with self.assertRaisesRegex(ScheduleValidationError, "UNKNOWN_DEPENDENCY"):
            self.scheduler.plan(tasks)

    def test_cycle_is_rejected_fail_closed(self) -> None:
        tasks = [
            RuntimeTaskSpec(
                task_id="a",
                agent_id="intelligence",
                depends_on=frozenset({"b"}),
            ),
            RuntimeTaskSpec(
                task_id="b",
                agent_id="strategist",
                depends_on=frozenset({"a"}),
            ),
        ]
        with self.assertRaisesRegex(ScheduleValidationError, "CYCLIC_DEPENDENCY_GRAPH"):
            self.scheduler.plan(tasks)

    def test_same_logical_agent_instances_execute_concurrently(self) -> None:
        barrier = threading.Barrier(3)
        tasks = [
            RuntimeTaskSpec(
                task_id=task_id,
                agent_id="intelligence",
                reads=frozenset({"objective"}),
                writes=frozenset({f"research.{task_id}"}),
            )
            for task_id in ("market", "competitors", "customers")
        ]

        def runner(task: RuntimeTaskSpec) -> str:
            barrier.wait(timeout=2.0)
            return task.task_id.upper()

        results = self.scheduler.execute(tasks, runner)

        self.assertEqual(
            results,
            {
                "market": "MARKET",
                "competitors": "COMPETITORS",
                "customers": "CUSTOMERS",
            },
        )

    def test_parallel_completion_order_cannot_change_merge_order(self) -> None:
        second_finished = threading.Event()
        tasks = [
            RuntimeTaskSpec(
                task_id="first",
                agent_id="intelligence",
                writes=frozenset({"research.first"}),
            ),
            RuntimeTaskSpec(
                task_id="second",
                agent_id="intelligence",
                writes=frozenset({"research.second"}),
            ),
        ]

        def runner(task: RuntimeTaskSpec) -> str:
            if task.task_id == "second":
                second_finished.set()
                return "finished-second"
            self.assertTrue(second_finished.wait(timeout=2.0))
            return "finished-first"

        results = self.scheduler.execute(tasks, runner)

        self.assertEqual(list(results), ["first", "second"])
        self.assertEqual(results["first"], "finished-first")
        self.assertEqual(results["second"], "finished-second")

    def test_compiler_derives_parallel_and_sequential_waves_from_task_kinds(self) -> None:
        compiler = AdaptiveTaskCompiler(scheduler=self.scheduler)
        compiled = compiler.compile([
            {"kind": "intelligence.market", "instruction": "Study the market"},
            {"kind": "intelligence.competitors", "instruction": "Study competitors"},
            {"kind": "intelligence.customers", "instruction": "Study customers"},
            {"kind": "strategist.positioning", "instruction": "Build positioning"},
            {"kind": "creative.angles", "instruction": "Create angles"},
        ])

        self.assertFalse(compiled.fallback_required)
        self.assertEqual(
            compiled.execution_plan.waves,
            (
                (
                    "intelligence-market",
                    "intelligence-competitors",
                    "intelligence-customers",
                ),
                ("strategist-positioning",),
                ("creative-angles",),
            ),
        )

    def test_model_cannot_self_authorize_parallelism_or_remove_dependencies(self) -> None:
        compiler = AdaptiveTaskCompiler(scheduler=self.scheduler)
        compiled = compiler.compile([
            {
                "kind": "intelligence.market",
                "instruction": "research",
                "side_effecting": False,
                "resource_scope_known": True,
                "depends_on": [],
                "writes": [],
                "parallel": True,
            },
            {
                "kind": "strategist.positioning",
                "instruction": "strategy",
                "side_effecting": False,
                "resource_scope_known": True,
                "depends_on": [],
                "writes": [],
                "parallel": True,
            },
        ])

        by_kind = {task.task_kind: task for task in compiled.tasks}
        strategy = by_kind["strategist.positioning"]
        self.assertEqual(strategy.depends_on, frozenset({"intelligence-market"}))
        self.assertEqual(strategy.writes, frozenset({"isolated.strategy.positioning"}))
        self.assertEqual(
            compiled.execution_plan.waves,
            (("intelligence-market",), ("strategist-positioning",)),
        )

    def test_unknown_planner_kinds_fail_closed_without_gaining_authority(self) -> None:
        compiler = AdaptiveTaskCompiler(scheduler=self.scheduler)
        mixed = compiler.compile([
            {"kind": "attacker.publish-everything", "parallel": True},
            {"kind": "intelligence.market", "instruction": "valid"},
        ])
        self.assertEqual(mixed.rejected_kinds, ("attacker.publish-everything",))
        self.assertEqual(mixed.execution_plan.waves, (("intelligence-market",),))

        all_unknown = compiler.compile([
            {"kind": "attacker.publish-everything", "parallel": True},
        ])
        self.assertTrue(all_unknown.fallback_required)
        self.assertEqual(all_unknown.execution_plan.mode, "SEQUENTIAL_FALLBACK")
        self.assertEqual(all_unknown.execution_plan.waves, ())


if __name__ == "__main__":
    unittest.main()
