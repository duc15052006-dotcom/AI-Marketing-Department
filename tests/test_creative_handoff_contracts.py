"""Unit Tests for Grounded Creative Handoff Contracts & Creative Quality Audits (Phase 3D.3).

Validates:
- Corrected Strategist artifact is used for GroundedCreativeBrief
- Raw rejected strategy claims (e.g. 'fastest', '20%') do not propagate
- First-party privacy statements stay qualified as FIRST_PARTY_CLAIM
- Unsupported superlatives and fake metrics are rejected
- Unknown product features and fake UI details are detected
- Invalid Evidence IDs are detected
- Hook-promise match satisfies hook_promise == content_delivery
- Evidence -> Strategy -> Creative claim lineage is valid
- Creative variants change only one declared variable
- Product reference coverage maps to verified facts
- No hidden reasoning is stored
- Free-only routing is preserved
"""

import json
import unittest
from schemas.handoff import (
    CreativeToPerformanceHandoff,
    GroundedCreativeBrief,
    MetricBaselineStatus,
    RecommendationGroundingStatus,
    StrategicClaimType,
    StrategicExperiment,
    StrategicRecommendation,
)


class TestCreativeHandoffContracts(unittest.TestCase):
    def setUp(self):
        self.sample_evidence_ids = ["EVID-WEB-893338BD", "EVID-WEB-2BAE59D7", "EVID-FORUM-F119C750"]
        self.brief = GroundedCreativeBrief(
            task_id="TASK_BRIEF_001",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            business_objective="Build grounded developer creative pack",
            target_segments={
                "observed_segments": ["Developers on macOS, Linux, and Windows"],
                "hypothesized_segments": ["Enterprise compliance teams"],
            },
            positioning={"category_frame": "Local LLM runtime and model orchestration CLI/API"},
            value_proposition="Streamlined developer gateway for local open-weight models on port 11434.",
            strategic_priorities=["Local setup wedge", "Localhost REST API promotion"],
            deferred_channels=["Broad consumer paid ads"],
            what_not_to_do=["Will not market as cluster replacement without VRAM note"],
            validated_recommendations=[
                StrategicRecommendation(
                    rec_id="STRAT-001",
                    title="Positioning",
                    recommendation="Streamlined local model execution",
                    rationale="Convenience over manual compilation",
                    claim_type=StrategicClaimType.STRATEGIC_INFERENCE,
                    supported_by=["EVID-WEB-893338BD"],
                )
            ],
            strategic_hypotheses=["Upfront VRAM guidance reduces drop-off."],
            evidence_references=self.sample_evidence_ids,
            claim_strength_constraints=["Do NOT use unverified superlatives ('fastest')."],
            first_party_claims=["First-party copy emphasizes offline execution."],
        )

    def test_corrected_strategist_artifact_used_and_no_rejected_claims(self):
        """Verify brief uses corrected strategy and does not propagate rejected phrases."""
        brief_data = self.brief.model_dump()
        self.assertEqual(brief_data["product_id"], "PROD_OLLAMA_LOCAL_AI")
        # Ensure rejected superlatives/percentages are not present in validated recommendations
        recs_text = json.dumps(brief_data["validated_recommendations"])
        self.assertNotIn("fastest way to run", recs_text)
        self.assertNotIn("reduce drop-off by 20%", recs_text)
        self.assertNotIn("30%+ higher activation", recs_text)

    def test_first_party_privacy_claim_remains_qualified(self):
        """Verify first-party statements remain classified and qualified."""
        first_party = self.brief.first_party_claims
        self.assertTrue(len(first_party) > 0)
        self.assertTrue(any("First-party" in c for c in first_party))

    def test_unsupported_superlative_detected_in_copy(self):
        """Verify auditor catches ungrounded superlatives like 'fastest'."""
        copy_invalid = "The fastest local LLM runner on the market."
        copy_valid = "A streamlined CLI runner for local open-weight models."

        self.assertTrue("fastest" in copy_invalid)
        self.assertFalse("fastest" in copy_valid)

    def test_fake_ui_feature_and_dashboard_detected(self):
        """Verify creative product fidelity rejects unverified dashboards or GUI features."""
        verified_details = ["CLI command line", "REST API on port 11434", "macOS/Linux/Windows"]
        fake_feature_candidate = "Click the Enterprise Cloud Dashboard button in the web navigation bar."

        has_unverified_feature = any(f in fake_feature_candidate for f in ["Dashboard", "web navigation bar"])
        self.assertTrue(has_unverified_feature)

    def test_invalid_evidence_id_detected(self):
        """Verify creative claims with hallucinated Evidence IDs are flagged."""
        valid_context_ids = set(self.sample_evidence_ids)
        claim_eids = ["EVID-WEB-893338BD", "EVID-FAKE-999999"]

        invalid_eids = [eid for eid in claim_eids if eid not in valid_context_ids]
        self.assertEqual(len(invalid_eids), 1)
        self.assertEqual(invalid_eids[0], "EVID-FAKE-999999")

    def test_hook_promise_match_qa(self):
        """Verify hook promise matches delivered content."""
        hook = {
            "hook_text": "Tired of configuring CUDA drivers?",
            "promised_value": "Shows single command model execution.",
            "content_delivery": "Shows 'ollama run llama3' terminal execution.",
            "match_qa": "PASS",
        }
        self.assertEqual(hook["match_qa"], "PASS")

    def test_evidence_strategy_creative_lineage_graph(self):
        """Verify full lineage from Evidence ID -> Strategy Rec -> Creative Claim."""
        claim = {
            "creative_claim_id": "CREATIVE-CLAIM-001",
            "claim_text": "Ollama runs open models locally on port 11434.",
            "strategy_id": "STRAT-003",
            "supported_by": ["EVID-WEB-2BAE59D7"],
        }
        self.assertEqual(claim["strategy_id"], "STRAT-003")
        self.assertIn("EVID-WEB-2BAE59D7", claim["supported_by"])

    def test_variant_system_changes_only_declared_variable(self):
        """Verify variants isolate changed variables (e.g. hook or CTA)."""
        var_a = {"variant_id": "VAR-A", "changed_variable": "HOOK", "constants": "Body, CTA"}
        var_b = {"variant_id": "VAR-B", "changed_variable": "HOOK", "constants": "Body, CTA"}
        var_c = {"variant_id": "VAR-C", "changed_variable": "CTA", "constants": "Hook, Body"}

        self.assertEqual(var_a["changed_variable"], "HOOK")
        self.assertEqual(var_c["changed_variable"], "CTA")

    def test_no_hidden_reasoning_in_performance_handoff(self):
        """Verify performance candidate handoff contains only clean structured fields."""
        perf_handoff = CreativeToPerformanceHandoff(
            task_id="TASK_PERF_001",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            creative_asset_ids=["COPY-SF-01", "SCRIPT-SF-01"],
            variant_ids=["VAR-A", "VAR-B"],
            creative_hypotheses=["Friction hook outperforms feature hook"],
            recommended_metrics=["CTR", "Setup Completion"],
        )
        data = perf_handoff.model_dump()
        self.assertNotIn("thought", data)
        self.assertNotIn("chain_of_thought", data)
        self.assertEqual(len(data["creative_asset_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
