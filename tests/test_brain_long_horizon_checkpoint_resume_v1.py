"""Adversarial contract tests for Long-Horizon Checkpoint/Resume Cognition V1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.checkpoint_resume as checkpoint_resume
from brain.autonomous_loop import AutonomousCognitiveLoopRequest
from brain.checkpoint_resume import (
    CheckpointResumeRequest,
    CognitiveCheckpoint,
    ResumeDirectiveKind,
    ResumeDisposition,
    resume_cognition,
)
from brain.cognitive_loop import CognitiveCycleRequest, CognitivePhase
from brain.contracts import BrainAgentId, GoalSpec, GoalStatus
from brain.metacognition import KnowledgeGap, KnowledgeGapKind, MetacognitionRequest
from brain.planning import PlanSnapshot, PlanStatus, PlanStep
from brain.world_state import (
    BeliefRevision,
    BeliefStatus,
    WorldBelief,
    WorldProposition,
    WorldStateSnapshot,
)
from schemas.base import ValidationError


class BrainLongHorizonCheckpointResumeV1Tests(unittest.TestCase):
    @staticmethod
    def _goal(*, status: GoalStatus = GoalStatus.OPEN, owner: BrainAgentId = BrainAgentId.CMO, objective: str = "Improve campaign outcome") -> GoalSpec:
        return GoalSpec(
            goal_id="G-1",
            objective=objective,
            owner_agent=owner,
            success_criteria=["Outcome improves"],
            constraints=["Evidence-backed only"],
            status=status,
        )

    @classmethod
    def _plan(
        cls,
        *,
        plan_id: str = "P-1",
        revision: int = 1,
        status: PlanStatus = PlanStatus.ACTIVE,
    ) -> PlanSnapshot:
        return PlanSnapshot(
            plan_id=plan_id,
            goal_id="G-1",
            revision=revision,
            parent_revision=(revision - 1 if revision > 1 else None),
            revision_reason=("new evidence" if revision > 1 else None),
            status=status,
            steps=[
                PlanStep(
                    step_id="S-1",
                    goal_id="G-1",
                    owner_agent=BrainAgentId.CMO,
                    objective="Inspect current campaign state",
                )
            ],
        )

    @classmethod
    def _auto_request(
        cls,
        *,
        goal: GoalSpec | None = None,
        plan: PlanSnapshot | None = None,
        metacognition: MetacognitionRequest | None = None,
        loop_id: str = "AUTO-1",
    ) -> AutonomousCognitiveLoopRequest:
        goal = goal or cls._goal()
        return AutonomousCognitiveLoopRequest(
            loop_id=loop_id,
            cognitive_cycle=CognitiveCycleRequest(
                cycle_id=f"C-{loop_id}",
                goal=goal,
                plan=plan,
            ),
            metacognition=metacognition,
        )

    @staticmethod
    def _meta_gap() -> MetacognitionRequest:
        return MetacognitionRequest(
            assessment_id="M-1",
            goal_id="G-1",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=[
                KnowledgeGap(
                    gap_id="KG-1",
                    goal_id="G-1",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    kind=KnowledgeGapKind.EVIDENCE,
                    question="Did the environment change while suspended?",
                    consequence="Blind resume could use stale assumptions",
                )
            ],
        )

    @staticmethod
    def _world(snapshot_id: str, *, previous_snapshot_id: str | None = None) -> WorldStateSnapshot:
        proposition = WorldProposition(
            proposition_id="WP-1",
            goal_id="G-1",
            agent_id=BrainAgentId.CMO,
            statement="Campaign state has been observed",
        )
        revision = BeliefRevision(
            revision_id=f"BR-{snapshot_id}",
            snapshot_id=snapshot_id,
            status=BeliefStatus.UNKNOWN,
            reasons=["Checkpoint continuity fixture"],
        )
        belief = WorldBelief(
            proposition=proposition,
            status=BeliefStatus.UNKNOWN,
            revisions=[revision],
        )
        return WorldStateSnapshot(
            snapshot_id=snapshot_id,
            goal_id="G-1",
            agent_id=BrainAgentId.CMO,
            previous_snapshot_id=previous_snapshot_id,
            beliefs=[belief],
            reasons=["Checkpoint continuity fixture"],
        )

    @classmethod
    def _checkpoint(
        cls,
        *,
        request: AutonomousCognitiveLoopRequest | None = None,
        world: WorldStateSnapshot | None = None,
        sequence: int = 1,
        checkpoint_id: str = "CP-1",
        previous_checkpoint_id: str | None = None,
    ) -> CognitiveCheckpoint:
        return CognitiveCheckpoint(
            checkpoint_id=checkpoint_id,
            sequence=sequence,
            previous_checkpoint_id=previous_checkpoint_id,
            agent_id=BrainAgentId.CMO,
            autonomous_request=request or cls._auto_request(),
            world_state=world,
            reason="Suspend long-horizon cognition safely",
        )

    @classmethod
    def _resume_request(
        cls,
        *,
        checkpoint: CognitiveCheckpoint | None = None,
        current_request: AutonomousCognitiveLoopRequest | None = None,
        current_world: WorldStateSnapshot | None = None,
        observed_latest_checkpoint_id: str | None = None,
        observed_latest_sequence: int | None = None,
    ) -> CheckpointResumeRequest:
        checkpoint = checkpoint or cls._checkpoint()
        return CheckpointResumeRequest(
            resume_id="RESUME-1",
            checkpoint=checkpoint,
            observed_latest_checkpoint_id=(
                observed_latest_checkpoint_id or checkpoint.checkpoint_id
            ),
            observed_latest_sequence=(
                observed_latest_sequence
                if observed_latest_sequence is not None
                else checkpoint.sequence
            ),
            current_request=current_request or cls._auto_request(loop_id="AUTO-NOW"),
            current_world_state=current_world,
        )

    def test_identical_semantic_state_can_resume_without_execution_authority(self) -> None:
        result = resume_cognition(self._resume_request())
        self.assertEqual(result.disposition, ResumeDisposition.RESUME)
        self.assertEqual(result.directive.kind, ResumeDirectiveKind.RESUME_COGNITION)
        self.assertEqual(result.autonomous_decision.phase, CognitivePhase.PLANNING)

    def test_terminal_goal_never_resumes(self) -> None:
        current = self._auto_request(
            goal=self._goal(status=GoalStatus.SATISFIED), loop_id="AUTO-NOW"
        )
        result = resume_cognition(self._resume_request(current_request=current))
        self.assertEqual(result.disposition, ResumeDisposition.TERMINAL)
        self.assertEqual(result.directive.kind, ResumeDirectiveKind.STOP)
        self.assertEqual(result.autonomous_decision.phase, CognitivePhase.COMPLETE)

    def test_blocked_goal_requires_reassessment_instead_of_blind_resume(self) -> None:
        current = self._auto_request(
            goal=self._goal(status=GoalStatus.BLOCKED), loop_id="AUTO-NOW"
        )
        result = resume_cognition(self._resume_request(current_request=current))
        self.assertEqual(result.disposition, ResumeDisposition.REASSESS_REQUIRED)
        self.assertEqual(result.directive.kind, ResumeDirectiveKind.REASSESS)

    def test_current_knowledge_gap_requires_research_before_resume(self) -> None:
        current = self._auto_request(
            metacognition=self._meta_gap(), loop_id="AUTO-NOW"
        )
        result = resume_cognition(self._resume_request(current_request=current))
        self.assertEqual(result.disposition, ResumeDisposition.RESEARCH_REQUIRED)
        self.assertEqual(result.directive.kind, ResumeDirectiveKind.RESEARCH)
        self.assertEqual(result.autonomous_decision.phase, CognitivePhase.RESEARCH)

    def test_plan_marked_needs_revision_routes_to_replan(self) -> None:
        checkpoint = self._checkpoint(request=self._auto_request(plan=self._plan()))
        current = self._auto_request(
            plan=self._plan(status=PlanStatus.NEEDS_REVISION), loop_id="AUTO-NOW"
        )
        result = resume_cognition(
            self._resume_request(checkpoint=checkpoint, current_request=current)
        )
        self.assertEqual(result.disposition, ResumeDisposition.REPLAN_REQUIRED)
        self.assertEqual(result.directive.kind, ResumeDirectiveKind.REPLAN)

    def test_new_contiguous_plan_revision_requires_reassessment(self) -> None:
        checkpoint = self._checkpoint(request=self._auto_request(plan=self._plan()))
        current = self._auto_request(plan=self._plan(revision=2), loop_id="AUTO-NOW")
        result = resume_cognition(
            self._resume_request(checkpoint=checkpoint, current_request=current)
        )
        self.assertEqual(result.disposition, ResumeDisposition.REASSESS_REQUIRED)

    def test_plan_revision_rollback_fails_closed(self) -> None:
        checkpoint = self._checkpoint(
            request=self._auto_request(plan=self._plan(revision=2))
        )
        current = self._auto_request(plan=self._plan(revision=1), loop_id="AUTO-NOW")
        with self.assertRaises(ValidationError):
            resume_cognition(
                self._resume_request(checkpoint=checkpoint, current_request=current)
            )

    def test_changed_plan_identity_routes_to_replan(self) -> None:
        checkpoint = self._checkpoint(request=self._auto_request(plan=self._plan()))
        current = self._auto_request(
            plan=self._plan(plan_id="P-NEW"), loop_id="AUTO-NOW"
        )
        result = resume_cognition(
            self._resume_request(checkpoint=checkpoint, current_request=current)
        )
        self.assertEqual(result.disposition, ResumeDisposition.REPLAN_REQUIRED)

    def test_new_world_snapshot_requires_reassessment(self) -> None:
        old_world = self._world("W-1")
        new_world = self._world("W-2", previous_snapshot_id="W-1")
        checkpoint = self._checkpoint(world=old_world)
        result = resume_cognition(
            self._resume_request(checkpoint=checkpoint, current_world=new_world)
        )
        self.assertEqual(result.disposition, ResumeDisposition.REASSESS_REQUIRED)
        self.assertEqual(result.directive.target_ids, ["W-2"])

    def test_broken_world_snapshot_lineage_fails_closed(self) -> None:
        checkpoint = self._checkpoint(world=self._world("W-1"))
        unrelated = self._world("W-9", previous_snapshot_id="W-X")
        with self.assertRaises(ValidationError):
            resume_cognition(
                self._resume_request(checkpoint=checkpoint, current_world=unrelated)
            )

    def test_stale_checkpoint_observation_fails_closed(self) -> None:
        checkpoint = self._checkpoint()
        with self.assertRaises(ValidationError):
            resume_cognition(
                self._resume_request(
                    checkpoint=checkpoint,
                    observed_latest_checkpoint_id="CP-NEWER",
                    observed_latest_sequence=2,
                )
            )

    def test_immutable_goal_identity_drift_fails_closed(self) -> None:
        current = self._auto_request(
            goal=self._goal(objective="Silently changed objective"),
            loop_id="AUTO-NOW",
        )
        with self.assertRaises(ValidationError):
            resume_cognition(self._resume_request(current_request=current))

    def test_checkpoint_sequence_requires_explicit_lineage(self) -> None:
        with self.assertRaises(ValidationError):
            self._checkpoint(sequence=2, checkpoint_id="CP-2")

    def test_no_sixth_agent_can_own_a_checkpoint(self) -> None:
        with self.assertRaises(ValidationError):
            CognitiveCheckpoint(
                checkpoint_id="CP-X",
                sequence=1,
                agent_id="SIXTH",
                autonomous_request=self._auto_request(),
                reason="invalid",
            )

    def test_serialized_request_reconstructs_canonical_nested_types(self) -> None:
        world = self._world("W-1")
        request = self._resume_request(
            checkpoint=self._checkpoint(world=world), current_world=world
        )
        reconstructed = CheckpointResumeRequest(**request.model_dump())
        result = resume_cognition(reconstructed)
        self.assertEqual(result.disposition, ResumeDisposition.RESUME)
        self.assertEqual(result.checkpoint_id, "CP-1")

    def test_post_construction_nested_mutation_is_revalidated_at_use_boundary(self) -> None:
        request = self._resume_request()
        request.checkpoint.autonomous_request.cognitive_cycle.goal.goal_id = "G-FORGED"
        with self.assertRaises(ValidationError):
            resume_cognition(request)

    def test_result_is_detached_from_caller_mutation(self) -> None:
        request = self._resume_request()
        result = resume_cognition(request)
        request.current_request.cognitive_cycle.goal.objective = "mutated"
        request.checkpoint.reason = "mutated"
        self.assertEqual(result.autonomous_decision.cognitive_cycle.goal.objective, "Improve campaign outcome")
        self.assertNotEqual(result.directive.rationale, "mutated")

    def test_checkpoint_resume_remains_semantic_only_provider_and_persistence_neutral(self) -> None:
        source = inspect.getsource(checkpoint_resume)
        tree = ast.parse(source)
        forbidden = {
            "runtime", "tools", "integrations", "connectors", "providers",
            "persistence", "scheduler", "queue", "sqlite3",
        }
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
        self.assertEqual(roots & forbidden, set())

        output = resume_cognition(self._resume_request()).model_dump()
        forbidden_fields = {
            "provider", "tool", "endpoint", "execution_authority", "file_path",
            "database", "queue", "worker", "schedule", "confidence", "probability",
        }
        self.assertFalse(set(output) & forbidden_fields)
        self.assertEqual(len(list(BrainAgentId)), 5)


if __name__ == "__main__":
    unittest.main()
