"""Regression tests for governed Memory Manager v1."""

import unittest
from datetime import datetime, timedelta, timezone

from memory.lifecycle_models import MemoryLifecycleState, MemoryScope
from memory.manager import MemoryManager
from memory.models import MemoryType, PromotionState


class MemoryManagerV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = MemoryManager()

    def test_exact_scope_isolation_plus_global_fallback(self) -> None:
        global_mem = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Global lesson about customer proof.",
        )
        alpha = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Project alpha customer proof lesson.",
            scope=MemoryScope(project_id="A"),
        )
        beta = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Project beta customer proof lesson.",
            scope=MemoryScope(project_id="B"),
        )

        results = self.manager.retrieve("proof", scope=MemoryScope(project_id="A"), include_global=True)
        ids = {memory.memory_id for memory in results}
        self.assertIn(global_mem.memory_id, ids)
        self.assertIn(alpha.memory_id, ids)
        self.assertNotIn(beta.memory_id, ids)

    def test_new_memory_cannot_enter_as_verified_or_promoted(self) -> None:
        verified = self.manager.remember(
            memory_type=MemoryType.SUCCESS_FAILURE_MEMORY,
            agent_source="performance",
            content="This result should not bypass verification.",
            promotion_level=PromotionState.VERIFIED_MEMORY,
            evidence_refs=["EV-1"],
            confidence=0.95,
        )
        promoted = self.manager.remember(
            memory_type=MemoryType.SUCCESS_FAILURE_MEMORY,
            agent_source="performance",
            content="This result should not bypass promotion.",
            promotion_level=PromotionState.PROMOTED_LEARNING,
            evidence_refs=["EV-1"],
            confidence=0.95,
        )
        self.assertFalse(verified.success)
        self.assertEqual(verified.error_code, "PROMOTION_BYPASS_BLOCKED")
        self.assertFalse(promoted.success)

    def test_promotion_sequence_and_evidence_are_enforced(self) -> None:
        created = self.manager.remember(
            memory_type=MemoryType.SUCCESS_FAILURE_MEMORY,
            agent_source="performance",
            content="Creative with strong product proof improved conversion.",
            confidence=0.9,
        )
        memory_id = created.memory_id or ""

        skipped = self.manager.promote(memory_id, PromotionState.VERIFIED_MEMORY, supporting_evidence=["EV-1"])
        self.assertFalse(skipped.success)
        self.assertIn("PROMOTION_SEQUENCE_REQUIRED", skipped.reason)

        candidate = self.manager.promote(memory_id, PromotionState.CANDIDATE_MEMORY)
        self.assertTrue(candidate.success)

        no_evidence = self.manager.promote(memory_id, PromotionState.VERIFIED_MEMORY)
        self.assertFalse(no_evidence.success)
        self.assertIn("EVIDENCE_REQUIRED", no_evidence.reason)

        verified = self.manager.promote(
            memory_id,
            PromotionState.VERIFIED_MEMORY,
            supporting_evidence=["EV-1"],
        )
        self.assertTrue(verified.success)

        no_rationale = self.manager.promote(memory_id, PromotionState.PROMOTED_LEARNING)
        self.assertFalse(no_rationale.success)
        self.assertIn("REVIEW_RATIONALE_REQUIRED", no_rationale.reason)

        promoted = self.manager.promote(
            memory_id,
            PromotionState.PROMOTED_LEARNING,
            review_rationale="Validated against campaign telemetry.",
        )
        self.assertTrue(promoted.success)
        saved = self.manager.repository.get_memory(memory_id)
        self.assertEqual(saved.promotion_level, PromotionState.PROMOTED_LEARNING)
        self.assertIn("EV-1", saved.evidence_refs)

    def test_expired_working_memory_is_archived_not_hard_deleted(self) -> None:
        result = self.manager.remember(
            memory_type=MemoryType.WORKING_MEMORY,
            agent_source="cmo",
            content="Temporary run context for one execution.",
            expiry_or_review_date=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
        memory_id = result.memory_id or ""
        self.assertEqual(self.manager.retrieve("Temporary"), [])
        self.assertEqual(self.manager.expire_due(), 1)

        stored = self.manager.repository.get_memory(memory_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, MemoryLifecycleState.EXPIRED.value)
        events = self.manager.list_events(memory_id)
        self.assertEqual(events[-1].action, "EXPIRED")

    def test_retired_disproven_and_superseded_memory_are_not_retrieved(self) -> None:
        retired = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Retired pricing lesson.",
        )
        disproven = self.manager.remember(
            memory_type=MemoryType.EXPERIMENT_MEMORY,
            agent_source="performance",
            content="Disproven pricing lesson.",
        )
        old = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Old pricing lesson.",
            scope=MemoryScope(project_id="A"),
        )
        new = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="New pricing lesson.",
            scope=MemoryScope(project_id="A"),
        )

        self.assertTrue(self.manager.retire(retired.memory_id or "", reason="obsolete"))
        self.assertTrue(self.manager.disprove(disproven.memory_id or "", reason="experiment contradicted it"))
        self.assertTrue(self.manager.supersede(old.memory_id or "", new.memory_id or ""))

        self.assertEqual(self.manager.retrieve("Retired"), [])
        self.assertEqual(self.manager.retrieve("Disproven"), [])
        scoped = self.manager.retrieve("pricing lesson", scope=MemoryScope(project_id="A"), include_global=False)
        ids = {memory.memory_id for memory in scoped}
        self.assertNotIn(old.memory_id, ids)
        self.assertIn(new.memory_id, ids)

    def test_supersession_cannot_cross_scope_boundaries(self) -> None:
        a = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Scope A decision.",
            scope=MemoryScope(project_id="A"),
        )
        b = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Scope B decision.",
            scope=MemoryScope(project_id="B"),
        )
        self.assertFalse(self.manager.supersede(a.memory_id or "", b.memory_id or ""))

    def test_repository_returns_defensive_copies(self) -> None:
        created = self.manager.remember(
            memory_type=MemoryType.EPISODIC_MEMORY,
            agent_source="intelligence",
            content="Observed campaign episode.",
            context={"channel": "social"},
        )
        memory_id = created.memory_id or ""
        first = self.manager.repository.get_memory(memory_id)
        first.context["caller_mutation"] = True
        second = self.manager.repository.get_memory(memory_id)
        self.assertNotIn("caller_mutation", second.context)

    def test_deduplication_is_scope_local(self) -> None:
        first = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Use compact creative for this audience.",
            scope=MemoryScope(project_id="A"),
            context={"audience": "decor"},
        )
        duplicate = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Use compact creative for this audience.",
            scope=MemoryScope(project_id="A"),
            context={"audience": "decor"},
        )
        other_scope = self.manager.remember(
            memory_type=MemoryType.DECISION_MEMORY,
            agent_source="strategist",
            content="Use compact creative for this audience.",
            scope=MemoryScope(project_id="B"),
            context={"audience": "decor"},
        )
        self.assertEqual(duplicate.duplicate_of, first.memory_id)
        self.assertNotEqual(other_scope.memory_id, first.memory_id)


if __name__ == "__main__":
    unittest.main()
