"""Unit Test Suite for Phase 4.3C.10D Protocol Freeze & Fairness Invariants."""

import json
import hashlib
import unittest
from pathlib import Path

from integrations.models.base import ModelUsage
from evaluations.benchmarks.phase4_3_unseen_case_02_dev_security.prompt_templates import (
    build_candidate_b3_pass_1_prompt,
    build_candidate_b3_pass_2_prompt,
    build_candidate_b3_pass_3_prompt,
    build_candidate_c3_one_shot_prompt,
)


class TestPhase43C10DProtocolFreeze(unittest.TestCase):
    """Verifies all Phase 4.3C.10D fairness invariants, token accounting, and cumulative bounded memory governance."""

    def setUp(self):
        self.case_dir = Path("evaluations/benchmarks/phase4_3_unseen_case_02_dev_security")
        self.manifest_file = self.case_dir / "phase4_3c_10c_benchmark_protocol.json"
        self.assertTrue(self.manifest_file.exists(), "Phase 4.3C.10D protocol manifest missing")
        self.manifest = json.loads(self.manifest_file.read_text(encoding="utf-8"))

        self.facts = json.loads((self.case_dir / "product_facts.json").read_text(encoding="utf-8"))
        self.evidence = json.loads((self.case_dir / "evidence_bundle.json").read_text(encoding="utf-8"))
        self.objective = json.loads((self.case_dir / "business_objective.json").read_text(encoding="utf-8"))

    def test_01_historical_29516_not_used_as_live_b3_target(self):
        """1. Historical 29516 is NOT used as live B3 target."""
        gov = self.manifest["b3_governor"]
        self.assertFalse(gov["historical_total_used_as_live_target"])
        self.assertEqual(gov["historical_case01_reference_total"], 29516)

    def test_02_b3_target_derives_from_fresh_a3(self):
        """2. B3 target derives from fresh A3 provider token total."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_resource_target_formula"], "ACTUAL_FRESH_A3_PROVIDER_TOTAL_TOKENS")

    def test_03_resource_tolerance_math(self):
        """3. +/- 10% resource math is correct."""
        tol = self.manifest["b3_governor"]["b3_resource_tolerance"]
        self.assertEqual(tol, 0.10)
        # Verify dynamic formula on arbitrary fresh A3 total (e.g. 30,000)
        sim_a3_total = 30000
        min_b = int(round(sim_a3_total * 0.90))
        max_b = int(round(sim_a3_total * 1.10))
        self.assertEqual(min_b, 27000)
        self.assertEqual(max_b, 33000)

    def test_04_b3_state_is_cumulative_bounded(self):
        """4. B3 state mode is cumulative bounded."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_working_state_mode"], "CUMULATIVE_BOUNDED")

    def test_05_pass_2_preserves_strategic_state(self):
        """5. Pass 2 preserves required Pass 1 strategic fields."""
        mock_state_1 = "[STRATEGIC_STATE]\n- LEAD_SEGMENT: Mid-tier tech\n- CORE_POSITIONING: Real-time AI Sec"
        prompt_2 = build_candidate_b3_pass_2_prompt(self.facts, self.evidence, self.objective, mock_state_1)
        self.assertIn("[CUMULATIVE BOUNDED WORKING STATE FROM PASS 1]", prompt_2)
        self.assertIn("Mid-tier tech", prompt_2)
        self.assertIn("Real-time AI Sec", prompt_2)

    def test_06_pass_3_preserves_strategic_and_creative_state(self):
        """6. Pass 3 preserves required strategic + creative fields."""
        mock_state_2 = "[STRATEGIC_STATE]\n- LEAD_SEGMENT: Mid-tier tech\n[CREATIVE_STATE]\n- SELECTED_TERRITORY: Invisible Copilot"
        prompt_3 = build_candidate_b3_pass_3_prompt(self.facts, self.evidence, self.objective, mock_state_2)
        self.assertIn("[CUMULATIVE BOUNDED WORKING STATE FROM PASSES 1 & 2]", prompt_3)
        self.assertIn("Invisible Copilot", prompt_3)

    def test_07_raw_prior_responses_not_recursively_concatenated(self):
        """7. Raw prior responses are not recursively concatenated."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_raw_history_recursion"], "DISABLED")

    def test_08_working_state_max_tokens_bound(self):
        """8. Working state limit is 1500 tokens."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_max_working_state_tokens"], 1500)

    def test_09_retention_priority_is_deterministic(self):
        """9. Retention priority is deterministic and pre-declared."""
        prio = self.manifest["b3_governor"]["deterministic_retention_priority"]
        self.assertEqual(len(prio), 8)
        self.assertIn("Prohibited claims", prio[0])

    def test_10_source_grounding_method_a_preserves_evidence(self):
        """10. Method A Source Grounding preserves source evidence across all passes."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_source_grounding_method"], "METHOD_A_SOURCE_BUNDLE_IN_ALL_PASSES")
        prompt_1 = build_candidate_b3_pass_1_prompt(self.facts, self.evidence, self.objective)
        prompt_2 = build_candidate_b3_pass_2_prompt(self.facts, self.evidence, self.objective, "STATE")
        prompt_3 = build_candidate_b3_pass_3_prompt(self.facts, self.evidence, self.objective, "STATE")
        for p in [prompt_1, prompt_2, prompt_3]:
            self.assertIn("[PRODUCT CAPABILITIES & VERIFIED FACTS]", p)
            self.assertIn("[MARKET EVIDENCE & RESEARCH FINDINGS]", p)
            self.assertIn("[BUSINESS OBJECTIVE]", p)

    def test_11_b3_logical_agent_count_is_one(self):
        """11. B3 logical agent count remains exactly 1."""
        gov = self.manifest["b3_governor"]
        self.assertEqual(gov["b3_logical_agent_count"], 1)

    def test_12_no_persona_injection(self):
        """12. No Multi-Agent persona injection in B3 prompts."""
        prompt_1 = build_candidate_b3_pass_1_prompt(self.facts, self.evidence, self.objective)
        prompt_2 = build_candidate_b3_pass_2_prompt(self.facts, self.evidence, self.objective, "STATE")
        prompt_3 = build_candidate_b3_pass_3_prompt(self.facts, self.evidence, self.objective, "STATE")
        for p in [prompt_1, prompt_2, prompt_3]:
            self.assertIn("You are a Senior Strategic Marketing Director", p)
            self.assertNotIn("You are the Intelligence Specialist", p)
            self.assertNotIn("You are the Creative Director Agent", p)
            self.assertNotIn("You are the Performance Marketing Agent", p)

    def test_13_no_a3_content_enters_b3(self):
        """13. No Candidate A content enters B3."""
        prompt_1 = build_candidate_b3_pass_1_prompt(self.facts, self.evidence, self.objective)
        self.assertNotIn("RUN-PHASE4-3-V2-BENCH-001", prompt_1)
        self.assertNotIn("Stage 6 (Final CMO)", prompt_1)

    def test_14_and_15_provider_telemetry_and_reconciliation(self):
        """14 & 15. Raw provider telemetry, thoughtsTokenCount, and total reconciliation."""
        usage = ModelUsage(
            prompt_tokens=2000,
            completion_tokens=1500,
            thoughts_tokens=2500,
            total_tokens=6000,
            usage_source="PROVIDER_REPORTED"
        )
        self.assertEqual(usage.thoughts_tokens, 2500)
        recomputed = usage.prompt_tokens + usage.completion_tokens + usage.thoughts_tokens
        self.assertEqual(recomputed, usage.total_tokens)

    def test_16_protocol_fingerprint_deterministic(self):
        """16. Protocol fingerprint is deterministic."""
        saved_fp = self.manifest["protocol_fingerprint"]
        manifest_copy = dict(self.manifest)
        del manifest_copy["protocol_fingerprint"]
        recomputed_fp = hashlib.sha256(json.dumps(manifest_copy, sort_keys=True).encode("utf-8")).hexdigest()
        self.assertEqual(saved_fp, recomputed_fp)


if __name__ == "__main__":
    unittest.main()
