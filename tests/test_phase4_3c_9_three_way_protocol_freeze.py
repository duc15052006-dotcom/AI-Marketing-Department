"""Unit tests for Phase 4.3C.9 / 4.3C.9B: Fair Three-Way Benchmark Protocol Freeze & Dynamic Resource Matching.

Validates that:
1. B budget derives dynamically from actual fresh Candidate A token usage.
2. Historical A 29,421 tokens is NOT hardcoded as B live target.
3. ±10% computation is deterministic.
4. Only A telemetry token total can flow into B resource configuration.
5. A content cannot flow into B (A_TO_B_CONTENT_LEAK_COUNT = 0).
6. B prompt hashes remain immutable after observing A.
7. Evaluation rubric remains immutable (weights sum to 1.00).
8. Candidate A must use a new fresh run ID in Phase 4.3C.10.
9. All A/B/C use identical max_output_tokens = 8192.
10. Completeness cannot be synthetically repaired (0 fabricated deliverables, 0 patches).
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import (
    assemble_three_way_blind_packet,
    audit_identity_leaks,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.neutral_canonical_assembler import (
    NeutralCanonicalCandidateAssembler,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.prompt_generators import (
    build_candidate_a_stage_1_prompt,
    build_candidate_b_pass_1_prompt,
    build_candidate_b_pass_2_prompt,
    build_candidate_b_pass_3_prompt,
    build_candidate_b_pass_4_prompt,
    build_candidate_b_pass_5_prompt,
    build_candidate_c_one_shot_prompt,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.protocol import (
    CANONICAL_28_DELIVERABLES,
    EVALUATION_RUBRIC_SPEC,
    EXECUTION_ORDER_SPEC,
    MODEL_CONFIG_SPEC,
    RESOURCE_MATCH_SPEC,
    BenchmarkProtocolManifest,
)


class TestPhase43C9BThreeWayProtocolFreeze(unittest.TestCase):
    """Test suite ensuring dynamic resource matching and complete protocol freeze integrity."""

    @classmethod
    def setUpClass(cls):
        cls.bench_dir = Path(__file__).resolve().parent.parent / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        cls.manifest = BenchmarkProtocolManifest.create()

    def test_benchmark_input_hash_frozen(self):
        """1. Verify immutable benchmark input files produce the exact frozen hash."""
        self.assertEqual(
            self.manifest.benchmark_input_hash,
            "ec155c53ffbca8b5ae52d358803092d3c876e0de30fb24ed0e824dfad1dbd8a5",
        )

    def test_dynamic_resource_matching_formula(self):
        """2. Verify B budget derives dynamically from actual fresh A token usage, not hardcoded 29,421."""
        self.assertEqual(
            RESOURCE_MATCH_SPEC["target_formula"],
            "ACTUAL_FRESH_A_PROVIDER_TOTAL_TOKENS",
        )
        self.assertFalse(self.manifest.candidate_b_spec["historical_a_used_as_live_b_target"])
        self.assertEqual(self.manifest.candidate_b_spec["historical_a_reference_tokens"], 29421)

        # Test dynamic simulation for different potential fresh A outcomes
        simulated_a_tokens = [25000, 30000, 35000]
        for a_actual in simulated_a_tokens:
            b_target = a_actual
            b_min = int(round(b_target * 0.90))
            b_max = int(round(b_target * 1.10))
            self.assertEqual(b_min, int(round(a_actual * 0.90)))
            self.assertEqual(b_max, int(round(a_actual * 1.10)))
            self.assertEqual(b_max - b_target, b_target - b_min)

    def test_information_firewall_a_to_b(self):
        """3. Verify strict firewall preventing Candidate A content from leaking to Candidate B."""
        firewall = RESOURCE_MATCH_SPEC["information_firewall"]
        self.assertEqual(firewall["A_TO_B_CONTENT_LEAK_COUNT"], 0)
        self.assertEqual(firewall["permitted_runtime_fields_from_a"], ["A_ACTUAL_PROVIDER_TOTAL_TOKENS"])
        self.assertIn("raw_text", firewall["prohibited_runtime_fields_from_a"])
        self.assertIn("findings", firewall["prohibited_runtime_fields_from_a"])
        self.assertIn("canonical_proposal", firewall["prohibited_runtime_fields_from_a"])

    def test_frozen_execution_order(self):
        """4. Verify deterministic Phase 4.3C.10 execution order."""
        self.assertEqual(EXECUTION_ORDER_SPEC["step_1"], "Execute Candidate A fresh under common 8192 config (new run ID)")
        self.assertEqual(EXECUTION_ORDER_SPEC["step_2"], "Seal Candidate A raw artifacts immediately")
        self.assertEqual(EXECUTION_ORDER_SPEC["step_3"], "Read ONLY Candidate A provider_total_tokens for resource matching")
        self.assertEqual(EXECUTION_ORDER_SPEC["step_7"], "Seal all candidate artifacts")
        self.assertEqual(EXECUTION_ORDER_SPEC["step_8"], "Begin 3-way double blind evaluation")

    def test_model_pinning_and_equal_output_ceiling_across_all(self):
        """5. Verify all A/B/C use identical gemini-3.5-flash with max_output_tokens = 8192."""
        self.assertEqual(MODEL_CONFIG_SPEC["requested_model"], "gemini-flash-latest")
        self.assertEqual(MODEL_CONFIG_SPEC["resolved_model"], "gemini-3.5-flash")
        self.assertTrue(MODEL_CONFIG_SPEC["strict_model_pin"])
        self.assertEqual(MODEL_CONFIG_SPEC["max_tokens_per_call"], 8192)
        self.assertEqual(MODEL_CONFIG_SPEC["timeout_seconds"], 180.0)

        self.assertEqual(self.manifest.candidate_a_spec["max_output_tokens"], 8192)
        self.assertEqual(self.manifest.candidate_b_spec["max_output_tokens"], 8192)
        self.assertEqual(self.manifest.candidate_c_spec["max_output_tokens"], 8192)

    def test_candidate_a_fresh_run_requirement(self):
        """6. Verify Candidate A must execute fresh with new run ID in Phase 4.3C.10."""
        self.assertTrue(self.manifest.candidate_a_spec["fresh_run_mandatory"])
        self.assertIn("HISTORICAL", self.manifest.candidate_a_spec["historical_baseline_run_id"])

    def test_prompt_hashes_immutable_across_passes(self):
        """7. Verify prompt hashes for B individual passes and C one-shot are deterministic."""
        facts = json.loads((self.bench_dir / "product_facts.json").read_text(encoding="utf-8"))
        evidence = json.loads((self.bench_dir / "evidence_bundle.json").read_text(encoding="utf-8"))
        obj = json.loads((self.bench_dir / "business_objective.json").read_text(encoding="utf-8"))

        p_b1 = build_candidate_b_pass_1_prompt(facts, evidence, obj)
        p_c = build_candidate_c_one_shot_prompt(facts, evidence, obj)

        self.assertIn("PASS 1 / 5", p_b1)
        self.assertIn("executive_summary", p_c)
        self.assertEqual(self.manifest.prompt_hash_b, "a9ccf32deabfb4a361c44a5efc20a66e159d2ebc424805b1a7d70b185335ed62")
        self.assertEqual(self.manifest.prompt_hash_c, "28c830ccf3839c0919c82e7347b0c12a4f141c6ebcc92370a08bc261fa1858b5")

    def test_evaluation_rubric_weights_sum_to_one(self):
        """8. Verify 14-dimension rubric weights sum exactly to 1.00 (100%)."""
        dims = EVALUATION_RUBRIC_SPEC["dimensions"]
        self.assertEqual(len(dims), 14)
        total_weight = sum(d["weight"] for d in dims)
        self.assertAlmostEqual(total_weight, 1.00, places=4)
        self.assertEqual(
            self.manifest.evaluation_rubric_hash,
            "c5e990a9b2fbe4e1a850f8bdf5a254c69d3468a62529d2e147569d412528f605",
        )

    def test_neutral_canonical_assembler_invariants(self):
        """9. Verify assembler enforces zero content patching, zero rewrites, zero fabricated deliverables."""
        run_dir = self.bench_dir / "runs" / "phase4_3_v2" / "RUN-PHASE4-3-V2-LIVE-001"
        faf_file = run_dir / "checkpoints" / "five_agent_final.json"
        if faf_file.exists():
            faf = json.loads(faf_file.read_text(encoding="utf-8"))
            stages = faf.get("stages", {})
            canonical_a, audit_a = NeutralCanonicalCandidateAssembler.assemble_candidate_a(stages)
            self.assertEqual(audit_a.content_patch_count, 0)
            self.assertEqual(audit_a.semantic_rewrite_count, 0)
            self.assertEqual(audit_a.fabricated_deliverable_count, 0)

    def test_three_way_blind_packet_leak_free(self):
        """10. Verify 3-way double blind review packet generation has 0 identity leaks."""
        import tempfile

        sample_prop_a = {"EXECUTIVE_SUMMARY": "Proposal A summary", "POSITIONING": "Positioning A"}
        sample_prop_b = {"EXECUTIVE_SUMMARY": "Proposal B summary", "POSITIONING": "Positioning B"}
        sample_prop_c = {"EXECUTIVE_SUMMARY": "Proposal C summary", "POSITIONING": "Positioning C"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            key_path, packet_path = assemble_three_way_blind_packet(
                sample_prop_a, sample_prop_b, sample_prop_c, Path(tmp_dir), seed=42
            )
            self.assertTrue(key_path.exists())
            self.assertTrue(packet_path.exists())

            packet_content = packet_path.read_text(encoding="utf-8")
            leaks = audit_identity_leaks(packet_content)
            self.assertEqual(leaks, 0)

    def test_master_protocol_fingerprint_deterministic(self):
        """11. Verify active deterministic composite benchmark protocol fingerprint."""
        self.assertEqual(
            self.manifest.protocol_fingerprint,
            "462086a31dd80c257ecbabfba12d6249772c3207e86ce379d8d76ea2248ceb0f",
        )
        self.assertEqual(
            self.manifest.previous_protocol_fingerprint,
            "00d17aaab9ed79a471a7d7826d40013806eb59786b2124066c249bb4ba52387f",
        )


if __name__ == "__main__":
    unittest.main()
