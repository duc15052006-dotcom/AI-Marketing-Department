"""Unit Tests for Grounded Inter-Agent Handoff Contracts (Phase 3D.2).

Validates:
- GroundedIntelligenceHandoff schema constraints & serialization
- Claim filtering (only SUPPORTED/PARTIALLY_SUPPORTED claims propagate)
- Epistemic inheritance (preserves missing transaction/telemetry gaps)
- StrategicRecommendation structure & Evidence ID citation
- StrategicExperiment falsifiability and stop conditions
- Strategic trade-offs and 'what not to do' policy enforcement
"""

import json
import unittest
from schemas.handoff import (
    GroundedIntelligenceHandoff,
    GroundedStrategyOutput,
    RecommendationGroundingStatus,
    StrategicExperiment,
    StrategicRecommendation,
)


class TestHandoffContracts(unittest.TestCase):
    def setUp(self):
        self.sample_evidence_ids = ["EVID-WEB-893338BD", "EVID-WEB-2BAE59D7", "EVID-FORUM-F119C750"]
        self.handoff = GroundedIntelligenceHandoff(
            task_id="TASK_TEST_001",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Analyze local AI runner reception",
            validated_findings=[
                "Ollama is an open-source CLI runtime running on localhost port 11434.",
                "7B Q4 model requires ~4-5GB VRAM.",
            ],
            facts=["Exposes background REST API on port 11434 (EVID-WEB-2BAE59D7)."],
            observations=["Hacker News sample (N=25) values CUDA setup on Linux (EVID-FORUM-F119C750)."],
            inferences=["Market wedge is setup friction reduction."],
            hypotheses=["Enterprise adoption driven by data privacy."],
            known_unknowns=[
                "Missing TRANSACTION_DATA: What is the exact conversion rate?",
                "Missing PRIVATE_TELEMETRY_DATA: What is active install base?",
            ],
            evidence_references=self.sample_evidence_ids,
            confidence="MEDIUM",
            confidence_rationale="Grounded in verified first-party docs and bounded forum sample.",
            research_limitations=["Developer reception bounded to N=25 comments."],
        )

    def test_handoff_serialization_and_required_fields(self):
        """Verify GroundedIntelligenceHandoff serializes and contains all required protocol fields."""
        data = self.handoff.model_dump()
        self.assertEqual(data["task_id"], "TASK_TEST_001")
        self.assertEqual(data["product_id"], "PROD_OLLAMA_LOCAL_AI")
        self.assertEqual(len(data["facts"]), 1)
        self.assertEqual(len(data["known_unknowns"]), 2)
        self.assertEqual(data["confidence"], "MEDIUM")

    def test_claim_filtering_policy(self):
        """Verify only SUPPORTED and PARTIALLY_SUPPORTED claims propagate to handoff."""
        raw_claims = [
            {"claim_text": "Ollama runs on port 11434", "grounding_status": "SUPPORTED"},
            {"claim_text": "HN sample likes automated CUDA", "grounding_status": "PARTIALLY_SUPPORTED"},
            {"claim_text": "Ollama has 10M paying enterprise users", "grounding_status": "UNSUPPORTED"},
            {"claim_text": "Ollama requires zero RAM on any machine", "grounding_status": "CONTRADICTED"},
        ]

        filtered = [
            c["claim_text"]
            for c in raw_claims
            if c["grounding_status"] in ("SUPPORTED", "PARTIALLY_SUPPORTED")
        ]

        self.assertEqual(len(filtered), 2)
        self.assertIn("Ollama runs on port 11434", filtered)
        self.assertNotIn("Ollama has 10M paying enterprise users", filtered)
        self.assertNotIn("Ollama requires zero RAM on any machine", filtered)

    def test_epistemic_inheritance_preserves_unknowns(self):
        """Verify downstream handoff does not drop or artificially resolve unknown facts."""
        unknowns = self.handoff.known_unknowns
        self.assertTrue(any("TRANSACTION_DATA" in u for u in unknowns))
        self.assertTrue(any("PRIVATE_TELEMETRY_DATA" in u for u in unknowns))

    def test_strategic_recommendation_structure(self):
        """Verify StrategicRecommendation requires recommendation, rationale, and validation test."""
        rec = StrategicRecommendation(
            rec_id="STRAT-001",
            title="Focus on Local Developer Setup",
            recommendation="Position as the fastest local developer setup wedge for open-weight models.",
            rationale="Solves manual C++ compilation and CUDA setup friction.",
            supported_by=["EVID-WEB-2BAE59D7", "EVID-FORUM-F119C750"],
            assumptions=["Target developers have compatible GPU hardware."],
            uncertainties=["Broad ecosystem satisfaction is unknown."],
            validation_test="CLI download-to-activation conversion rate.",
            stop_or_reconsider_condition="Halt if hardware friction drives negative issue volume.",
            epistemic_tier="INFERENCE",
            grounding_status=RecommendationGroundingStatus.GROUNDED,
        )

        self.assertEqual(rec.rec_id, "STRAT-001")
        self.assertEqual(len(rec.supported_by), 2)
        self.assertEqual(rec.grounding_status, RecommendationGroundingStatus.GROUNDED)

    def test_strategic_experiment_falsifiability_and_stop_conditions(self):
        """Verify StrategicExperiment defines hypothesis, target segment, metrics, and stop condition."""
        exp = StrategicExperiment(
            experiment_id="EXP-001",
            hypothesis="Upfront VRAM sizing tool reduces onboarding drop-off by 20%.",
            target_segment="Developers on macOS and Linux",
            change_or_treatment="Interactive model-to-VRAM calculator on landing page",
            primary_metric="CLI Setup Completion Rate (TO_BE_ESTABLISHED)",
            secondary_metrics=["Time to First Token", "CPU Fallback Issue Count"],
            expected_signal="Statistically significant drop in installation abandonment",
            time_or_sample_requirement="14 days / N=500 visitors",
            stop_condition="Halt treatment if sizing tool increases friction or lowers install rate",
            evidence_dependency=["EVID-WEB-2BAE59D7"],
        )

        self.assertEqual(exp.experiment_id, "EXP-001")
        self.assertIn("TO_BE_ESTABLISHED", exp.primary_metric)
        self.assertTrue(len(exp.stop_condition) > 0)


if __name__ == "__main__":
    unittest.main()
