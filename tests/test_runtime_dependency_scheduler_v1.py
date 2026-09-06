from __future__ import annotations

import unittest

from runtime.dependency_scheduler import DependencyAwareScheduler, RuntimeTaskSpec


class DependencyAwareSchedulerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = DependencyAwareScheduler()

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


if __name__ == "__main__":
    unittest.main()
