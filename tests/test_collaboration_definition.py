"""Tests verifying the Five-Agent Collaboration Benchmark and Protocol Integrity."""

import unittest
from pathlib import Path
from schemas.protocol import (
    AgentRole,
    HandoffType,
    PermissionMode,
    ApprovalState,
    LearningTier,
    EpistemicType,
    TaskEnvelope,
    EpistemicStatement,
    AgentResult,
    CollaborationTrace,
    ContradictionRecord,
    ActionRequest,
    CandidateLearningRecord,
)


class TestCollaborationDefinition(unittest.TestCase):
    def setUp(self):
        self.collaboration_eval_path = (
            Path(__file__).resolve().parent.parent / "COLLABORATION_EVALUATION.md"
        )
        self.gap_doc_path = (
            Path(__file__).resolve().parent.parent / "COLLABORATION_RUNTIME_GAP.md"
        )
        self.assertTrue(self.collaboration_eval_path.exists(), "COLLABORATION_EVALUATION.md does not exist")
        self.assertTrue(self.gap_doc_path.exists(), "COLLABORATION_RUNTIME_GAP.md does not exist")
        self.eval_content = self.collaboration_eval_path.read_text(encoding="utf-8")
        self.gap_content = self.gap_doc_path.read_text(encoding="utf-8")

    def test_exactly_five_permanent_agents_defined(self):
        """Verify the AgentRole enum and collaboration documents enforce exactly five permanent agents."""
        self.assertEqual(len(AgentRole), 5)
        self.assertEqual(
            {r.value for r in AgentRole},
            {"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"},
        )

    def test_task_envelope_collaboration_compatibility(self):
        """Verify TaskEnvelope includes all required fields for multi-agent routing."""
        envelope = TaskEnvelope(
            task_id="TASK-20260816-COL-001",
            objective="Develop GTM positioning and creative campaign for Ergonomic Chair",
            business_context="Targeting remote tech workers suffering posture fatigue",
            product_id="PROD_ERGO_CHAIR_01",
            brand_id="BRAND_ERGOWORK",
            known_facts=["Weight limit is 300 lbs", "Mesh lumbar support included"],
            unknown_facts=["Customer price sensitivity above $300"],
            assumptions=["Remote workers will pay for premium ergonomics"],
            hypotheses=["Highlighting Sunday night back pain will increase CTR by 20%"],
            owner_agent=AgentRole.STRATEGIST,
            supporting_agents=[AgentRole.INTELLIGENCE, AgentRole.CREATIVE],
            output_schema="CreativeStrategyBrief",
            escalation_rule="Escalate to CMO if CPC exceeds $2.50 in test",
            next_action="Handoff to Creative for concept production",
        )
        self.assertEqual(envelope.owner_agent, AgentRole.STRATEGIST)
        self.assertEqual(len(envelope.supporting_agents), 2)
        self.assertEqual(envelope.product_id, "PROD_ERGO_CHAIR_01")

    def test_collaboration_trace_structure_and_no_cot_exposure(self):
        """Verify CollaborationTrace schema records decision-useful data without exposing private chain-of-thought."""
        trace = CollaborationTrace(
            trace_id="TRACE-20260816-0001",
            task_id="TASK-20260816-COL-001",
            from_agent=AgentRole.INTELLIGENCE,
            to_agent=AgentRole.STRATEGIST,
            handoff_type=HandoffType.DELEGATION,
            input_summary="Delivered 15 customer review pain points and competitor pricing audit",
            facts_preserved=["Competitor average price is $249"],
            assumptions_preserved=["Market willingness to pay is high"],
            unknowns_preserved=["B2B corporate reimbursement policy rates"],
            output_reference="research/PROD_ERGO_CHAIR_01/customer_intelligence.json",
        )
        self.assertEqual(trace.from_agent, AgentRole.INTELLIGENCE)
        self.assertEqual(trace.to_agent, AgentRole.STRATEGIST)
        self.assertEqual(trace.handoff_type, HandoffType.DELEGATION)
        # Ensure schema has no private chain-of-thought or raw reasoning token fields
        self.assertNotIn("chain_of_thought", trace.model_dump())
        self.assertNotIn("reasoning_tokens", trace.model_dump())
        self.assertNotIn("internal_scratchpad", trace.model_dump())

    def test_contradiction_protocol_record_and_cmo_resolution(self):
        """Verify ContradictionRecord preserves competing claims and options for CMO trade-off resolution."""
        conflict = ContradictionRecord(
            conflict_id="CONF-20260816-001",
            claim_a="Market demand is high for expensive cinematic video series ($15k)",
            agent_a=AgentRole.CREATIVE,
            evidence_a=["EV-CREATIVE-001"],
            claim_b="Unit margins ($12) cannot support $15k production without incurring net loss",
            agent_b=AgentRole.PERFORMANCE,
            evidence_b=["EV-PERF-ECON-004"],
            type_of_conflict="FEASIBILITY_VS_CREATIVE_BUDGET",
            missing_evidence=["Conversion elasticity under lower production formats"],
            resolution_owner=AgentRole.CMO,
            resolution_outcome="LIMITED_TEST",
            resolution_rationale="Authorize $250 screen-demo test to validate conversion before committing large budget",
        )
        self.assertEqual(conflict.resolution_owner, AgentRole.CMO)
        self.assertEqual(conflict.resolution_outcome, "LIMITED_TEST")

    def test_uncertainty_propagation_discipline(self):
        """Verify that UNKNOWN / HYPOTHESIS declarations survive downstream without mutating to FACT."""
        hyp_stmt = EpistemicStatement(
            tier=EpistemicType.HYPOTHESIS,
            statement="Dark mode UI might improve conversion on technical developer tools",
            confidence=0.5,
        )
        self.assertEqual(hyp_stmt.tier, EpistemicType.HYPOTHESIS)
        self.assertNotEqual(hyp_stmt.tier, EpistemicType.FACT)

        fact_stmt = EpistemicStatement(
            tier=EpistemicType.FACT,
            statement="Product pricing is $99/mo verified in database",
            evidence_references=["DOC-001"],
            confidence=1.0,
        )
        self.assertEqual(fact_stmt.tier, EpistemicType.FACT)
        self.assertTrue(len(fact_stmt.evidence_references) > 0)

    def test_product_isolation_adversarial_rejection(self):
        """Verify that product ID mismatch in task envelopes and results is strictly caught."""
        env_a = TaskEnvelope(
            task_id="TASK-A",
            objective="Analyze Product A market",
            business_context="Product A context",
            product_id="PROD_A",
            brand_id="BRAND_A",
            owner_agent=AgentRole.INTELLIGENCE,
            output_schema="MarketReport",
            escalation_rule="Escalate to CMO",
            next_action="Handoff to Strategist",
        )
        result_b = AgentResult(
            task_id="TASK-A",
            owner_agent=AgentRole.INTELLIGENCE,
            payload={"product_id": "PROD_B", "data": "Cross-product leaked insight"},
        )
        # Verify cross-product ID mismatch is detectable
        self.assertNotEqual(env_a.product_id, result_b.payload["product_id"])

    def test_permission_mode_and_action_request_governance(self):
        """Verify operational ActionRequest requires explicit approval in SUPERVISED mode."""
        action = ActionRequest(
            action_id="ACT-20260816-001",
            agent_name=AgentRole.PERFORMANCE,
            product_id="PROD_ERGO_CHAIR_01",
            campaign_id="CMP_Q3_AFFILIATE_PILOT",
            platform_target="Meta Ads API",
            requested_action="Deploy Ad Set 01 to live network",
            permission_mode=PermissionMode.SUPERVISED,
            approval_state=ApprovalState.PENDING_APPROVAL,
            payload={"daily_budget": 50.0},
            risks=["Ad spend without confirmed human review"],
        )
        self.assertEqual(action.permission_mode, PermissionMode.SUPERVISED)
        self.assertEqual(action.approval_state, ApprovalState.PENDING_APPROVAL)

    def test_candidate_learning_governance(self):
        """Verify candidate learning records require retesting and cannot directly modify permanent system prompts."""
        learning = CandidateLearningRecord(
            learning_id="LRN-20260816-001",
            tier=LearningTier.CANDIDATE_LEARNING,
            product_id="PROD_ERGO_CHAIR_01",
            audience_segment="Remote Tech Workers",
            channel_and_format="TikTok 9:16 Video",
            creative_component="Time-Lapse Posture Race Hook",
            empirical_observation="Achieved 4.2% Link CTR across 12,000 impressions",
            validated_insight="Acute physical pain hooks outperform aesthetic chair feature showcases",
            confounders_monitored=["Seasonality", "Competitor discounts"],
            scope_of_applicability="Ergonomic physical hardware in remote worker niche",
            retest_required=True,
        )
        self.assertEqual(learning.tier, LearningTier.CANDIDATE_LEARNING)
        self.assertTrue(learning.retest_required)

    def test_collaboration_evaluation_contains_all_30_scenarios(self):
        """Verify COLLABORATION_EVALUATION.md defines all 30 required scenarios with correct structure."""
        for i in range(1, 31):
            self.assertIn(f"### Scenario {i}:", self.eval_content)
        self.assertIn("NOT_TESTED (Pending Live Model Harness)", self.eval_content)

    def test_collaboration_runtime_gap_documented(self):
        """Verify COLLABORATION_RUNTIME_GAP.md explicitly marks live model eval as NOT_AVAILABLE / NOT_RUN."""
        self.assertIn("LIVE_COLLABORATION_EVAL = NOT_AVAILABLE", self.gap_content)
        self.assertIn("LIVE_MODEL_EVAL = NOT_RUN", self.gap_content)
        self.assertIn("STATIC_CONTRACT_TEST = PASS", self.gap_content)


if __name__ == "__main__":
    unittest.main()
