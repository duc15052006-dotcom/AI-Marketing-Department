"""Adversarial contract tests for Safe Self-Improvement V1."""

from __future__ import annotations

import ast
import inspect
import unittest

import brain.safe_self_improvement as self_improvement
from brain.contracts import BrainAgentId
from brain.meta_learning import MetaLearningRequest, StrategyTrial
from brain.metacognition import (
    KnowledgeGap,
    KnowledgeGapKind,
    LearningStrategy,
    MetacognitionRequest,
)
from brain.safe_self_improvement import (
    LearningPolicySnapshot,
    SafeSelfImprovementDisposition,
    SafeSelfImprovementRequest,
    propose_safe_self_improvement,
)
from schemas.base import ValidationError


class BrainSafeSelfImprovementV1Tests(unittest.TestCase):
    @staticmethod
    def _meta_state(assessment_id: str, gap_count: int) -> MetacognitionRequest:
        return MetacognitionRequest(
            assessment_id=assessment_id,
            goal_id="G-LEARN",
            agent_id=BrainAgentId.INTELLIGENCE,
            gaps=[
                KnowledgeGap(
                    gap_id=f"KG-{assessment_id}-{index}",
                    goal_id="G-LEARN",
                    owner_agent=BrainAgentId.INTELLIGENCE,
                    kind=KnowledgeGapKind.EVIDENCE,
                    question=f"Unknown {index}",
                    consequence="Wrong learning policy can preserve uncertainty",
                    blocking=index == 0 and gap_count > 1,
                )
                for index in range(gap_count)
            ],
        )

    @classmethod
    def _trial(
        cls,
        trial_id: str,
        strategy: LearningStrategy,
        before_gaps: int,
        after_gaps: int,
    ) -> StrategyTrial:
        return StrategyTrial(
            trial_id=trial_id,
            problem_family_id="PF-MARKET-RESEARCH",
            strategy=strategy,
            before_request=cls._meta_state(f"B-{trial_id}", before_gaps),
            after_request=cls._meta_state(f"A-{trial_id}", after_gaps),
        )

    @classmethod
    def _meta_request(cls, mode: str = "prefer") -> MetaLearningRequest:
        if mode == "prefer":
            trials = [
                cls._trial("R-1", LearningStrategy.RESEARCH, 2, 0),
                cls._trial("R-2", LearningStrategy.RESEARCH, 1, 0),
                cls._trial("R-3", LearningStrategy.RESEARCH, 3, 1),
            ]
        elif mode == "insufficient":
            trials = [
                cls._trial("R-1", LearningStrategy.RESEARCH, 2, 0),
                cls._trial("R-2", LearningStrategy.RESEARCH, 1, 0),
            ]
        elif mode == "revise":
            trials = [
                cls._trial("R-1", LearningStrategy.RESEARCH, 0, 1),
                cls._trial("R-2", LearningStrategy.RESEARCH, 1, 2),
                cls._trial("R-3", LearningStrategy.RESEARCH, 1, 1),
            ]
        elif mode == "tie":
            trials = [
                cls._trial("R-1", LearningStrategy.RESEARCH, 1, 0),
                cls._trial("R-2", LearningStrategy.RESEARCH, 2, 0),
                cls._trial("R-3", LearningStrategy.RESEARCH, 3, 1),
                cls._trial("E-1", LearningStrategy.EXPERIMENT, 1, 0),
                cls._trial("E-2", LearningStrategy.EXPERIMENT, 2, 0),
                cls._trial("E-3", LearningStrategy.EXPERIMENT, 3, 1),
            ]
        else:
            raise AssertionError(mode)
        return MetaLearningRequest(
            assessment_id=f"ML-{mode}",
            problem_family_id="PF-MARKET-RESEARCH",
            policy_owner_agent=BrainAgentId.CMO,
            trials=trials,
        )

    @staticmethod
    def _policy(
        *,
        strategy: LearningStrategy | None = LearningStrategy.EXPERIMENT,
        problem_family_id: str = "PF-MARKET-RESEARCH",
        owner: BrainAgentId = BrainAgentId.CMO,
        revision: int = 4,
    ) -> LearningPolicySnapshot:
        return LearningPolicySnapshot(
            policy_id="LP-1",
            revision=revision,
            problem_family_id=problem_family_id,
            owner_agent=owner,
            preferred_strategy=strategy,
        )

    @classmethod
    def _request(
        cls,
        *,
        policy: LearningPolicySnapshot | None = None,
        meta: MetaLearningRequest | None = None,
    ) -> SafeSelfImprovementRequest:
        return SafeSelfImprovementRequest(
            improvement_id="SI-1",
            current_policy=policy or cls._policy(),
            meta_learning=meta or cls._meta_request("prefer"),
        )

    def test_repeated_canonical_improvement_can_only_propose_strategy_change(self) -> None:
        decision = propose_safe_self_improvement(self._request())
        self.assertEqual(
            decision.disposition,
            SafeSelfImprovementDisposition.PROPOSE_STRATEGY_CHANGE,
        )
        self.assertIsNotNone(decision.proposal)
        self.assertEqual(decision.proposal.current_strategy, LearningStrategy.EXPERIMENT)
        self.assertEqual(decision.proposal.proposed_strategy, LearningStrategy.RESEARCH)
        self.assertEqual(decision.proposal.from_revision, 4)
        self.assertEqual(decision.proposal.proposed_revision, 5)
        self.assertTrue(decision.proposal.requires_external_review)

    def test_preferred_strategy_already_active_is_no_change(self) -> None:
        decision = propose_safe_self_improvement(
            self._request(policy=self._policy(strategy=LearningStrategy.RESEARCH))
        )
        self.assertEqual(decision.disposition, SafeSelfImprovementDisposition.NO_CHANGE)
        self.assertIsNone(decision.proposal)

    def test_insufficient_meta_learning_evidence_cannot_change_policy(self) -> None:
        decision = propose_safe_self_improvement(
            self._request(meta=self._meta_request("insufficient"))
        )
        self.assertEqual(decision.disposition, SafeSelfImprovementDisposition.NO_CHANGE)
        self.assertIsNone(decision.proposal)

    def test_tied_strategies_cannot_change_policy(self) -> None:
        decision = propose_safe_self_improvement(
            self._request(meta=self._meta_request("tie"))
        )
        self.assertEqual(decision.disposition, SafeSelfImprovementDisposition.NO_CHANGE)
        self.assertIsNone(decision.proposal)

    def test_meta_learning_revision_request_requires_human_review_not_invented_policy(self) -> None:
        decision = propose_safe_self_improvement(
            self._request(meta=self._meta_request("revise"))
        )
        self.assertEqual(
            decision.disposition,
            SafeSelfImprovementDisposition.HUMAN_REVIEW_REQUIRED,
        )
        self.assertIsNone(decision.proposal)

    def test_problem_family_scope_must_bind_exactly(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                policy=self._policy(problem_family_id="PF-CREATIVE"),
                meta=self._meta_request("prefer"),
            )

    def test_policy_owner_must_bind_exactly(self) -> None:
        with self.assertRaises(ValidationError):
            self._request(
                policy=self._policy(owner=BrainAgentId.CONTENT),
                meta=self._meta_request("prefer"),
            )

    def test_none_cannot_be_smuggled_as_an_active_preferred_strategy(self) -> None:
        with self.assertRaises(ValidationError):
            self._policy(strategy=LearningStrategy.NONE)

    def test_policy_revision_must_be_positive(self) -> None:
        with self.assertRaises(ValidationError):
            self._policy(revision=0)

    def test_serialized_request_reconstructs_all_nested_canonical_types(self) -> None:
        request = self._request()
        reconstructed = SafeSelfImprovementRequest(**request.model_dump())
        decision = propose_safe_self_improvement(reconstructed)
        self.assertEqual(
            decision.disposition,
            SafeSelfImprovementDisposition.PROPOSE_STRATEGY_CHANGE,
        )
        self.assertEqual(decision.proposal.proposed_strategy, LearningStrategy.RESEARCH)

    def test_post_construction_nested_mutation_is_revalidated_at_use_boundary(self) -> None:
        request = self._request()
        request.meta_learning.trials[0].after_request.goal_id = "G-FORGED"
        with self.assertRaises(ValidationError):
            propose_safe_self_improvement(request)

    def test_post_construction_policy_scope_mutation_is_revalidated_at_use_boundary(self) -> None:
        request = self._request()
        request.current_policy.problem_family_id = "PF-FORGED"
        with self.assertRaises(ValidationError):
            propose_safe_self_improvement(request)

    def test_result_is_detached_from_caller_mutation(self) -> None:
        request = self._request()
        result = propose_safe_self_improvement(request)
        request.current_policy.policy_id = "MUTATED"
        request.meta_learning.trials[0].before_request.gaps[0].question = "mutated"
        self.assertEqual(result.policy_id, "LP-1")
        self.assertEqual(result.proposal.policy_id, "LP-1")
        self.assertNotIn("mutated", " ".join(result.reasons).lower())

    def test_module_exposes_no_apply_or_self_modification_operation(self) -> None:
        public_names = set(dir(self_improvement))
        forbidden = {
            "apply_self_improvement",
            "apply_policy_update",
            "modify_code",
            "write_policy",
            "deploy_policy",
            "grant_authority",
        }
        self.assertEqual(public_names & forbidden, set())

    def test_proposal_surface_cannot_launder_authority_or_arbitrary_policy_fields(self) -> None:
        decision = propose_safe_self_improvement(self._request())
        payload = decision.model_dump()
        proposal = payload["proposal"]
        forbidden = {
            "provider", "model", "tool", "endpoint", "credential", "permission",
            "approval", "execution_authority", "code", "code_path", "prompt",
            "runtime", "worker", "queue", "database", "file_path", "policy_field",
            "policy_value", "confidence", "probability",
        }
        self.assertFalse(set(payload) & forbidden)
        self.assertFalse(set(proposal) & forbidden)
        self.assertEqual(
            set(proposal),
            {
                "proposal_id",
                "policy_id",
                "problem_family_id",
                "owner_agent",
                "from_revision",
                "proposed_revision",
                "current_strategy",
                "proposed_strategy",
                "source_assessment_id",
                "requires_external_review",
                "reasons",
            },
        )

    def test_safe_self_improvement_remains_semantic_only_and_five_asi_bounded(self) -> None:
        source = inspect.getsource(self_improvement)
        tree = ast.parse(source)
        forbidden_roots = {
            "runtime", "tools", "integrations", "connectors", "providers",
            "persistence", "scheduler", "queue", "subprocess", "os", "pathlib",
        }
        roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.add(node.module.split(".", 1)[0])
        self.assertEqual(roots & forbidden_roots, set())
        self.assertEqual(len(list(BrainAgentId)), 5)

    def test_output_contains_canonical_meta_learning_provenance(self) -> None:
        decision = propose_safe_self_improvement(self._request())
        self.assertEqual(decision.source_assessment_id, "ML-prefer")
        self.assertEqual(decision.problem_family_id, "PF-MARKET-RESEARCH")
        self.assertEqual(decision.owner_agent, BrainAgentId.CMO)
        self.assertEqual(decision.meta_learning_decision.preferred_strategy, LearningStrategy.RESEARCH)


if __name__ == "__main__":
    unittest.main()
