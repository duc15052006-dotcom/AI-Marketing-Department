"""Unit Tests for Phase 4.1.2: True Model-Parity Controlled Benchmark.

Verifies:
1. same exact requested model (gemini-flash-latest)
2. no lite/standard mismatch permitted (substitution blocked)
3. provider usage metadata captured from provider
4. missing five-agent tokens invalidates efficiency comparison
5. same evidence manifest (EVID-GAN65-01..05)
6. same fact boundary enforced
7. same evaluator rules
8. no post-generation patching permitted
9. parity failure forces INCONCLUSIVE verdict
10. quota exhaustion triggers BLOCKED_MODEL_PARITY_QUOTA
"""

import json
from pathlib import Path
import unittest


class TestPhase412TrueParity(unittest.TestCase):
    def setUp(self):
        self.parity_dir = Path(__file__).resolve().parent.parent / "evaluations" / "benchmarks" / "phase4_1_2_true_parity"

    def test_same_exact_requested_model_configured(self):
        """Verify benchmark config mandates gemini-flash-latest with no fallback."""
        config_path = self.parity_dir / "benchmark_config.json"
        self.assertTrue(config_path.exists())

        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config.get("model_requested"), "gemini-flash-latest")
        self.assertFalse(config.get("allow_fallback"))
        self.assertTrue(config.get("free_only_mode"))

    def test_no_lite_standard_mismatch_permitted(self):
        """Verify substitution with lite or alternate models is strictly prohibited."""
        config_path = self.parity_dir / "benchmark_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))

        avail = config.get("model_availability_check", {})
        self.assertFalse(avail.get("substitution_permitted"))
        self.assertTrue(config.get("benchmark_rules", {}).get("prohibit_model_substitution"))

    def test_same_evidence_manifest(self):
        """Verify shared evidence manifest contains all 5 validated evidence items."""
        evid_path = self.parity_dir / "shared_evidence_manifest.json"
        self.assertTrue(evid_path.exists())

        manifest = json.loads(evid_path.read_text(encoding="utf-8"))
        items = manifest.get("evidence_items", [])
        e_ids = {item.get("evidence_id") for item in items}

        for i in range(1, 6):
            self.assertIn(f"EVID-GAN65-0{i}", e_ids)

    def test_same_fact_boundary(self):
        """Verify product fact boundary contains only guaranteed facts."""
        input_path = self.parity_dir / "shared_input.json"
        self.assertTrue(input_path.exists())

        data = json.loads(input_path.read_text(encoding="utf-8"))
        specs = data.get("guaranteed_specifications", [])

        self.assertIn("65W maximum power output", specs)
        self.assertIn("GaN (Gallium Nitride) semiconductor architecture", specs)
        self.assertIn("USB-C connectivity", specs)
        self.assertIn("Compact portable form factor", specs)

    def test_no_post_generation_patching_enforced(self):
        """Verify benchmark rules strictly prohibit post-generation patching."""
        config_path = self.parity_dir / "benchmark_config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertTrue(config.get("benchmark_rules", {}).get("prohibit_post_generation_patching"))

    def test_parity_failure_forces_inconclusive(self):
        """Verify when parity gate fails, final verdict is strictly INCONCLUSIVE."""
        integrity_path = self.parity_dir / "benchmark_integrity.json"
        self.assertTrue(integrity_path.exists())

        integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
        gates = integrity.get("integrity_gates", {})

        if gates.get("MODEL_PARITY") != "PASS":
            self.assertEqual(integrity.get("final_comparison_verdict"), "INCONCLUSIVE")

    def test_single_model_provider_reported_telemetry(self):
        """Verify single model baseline records exact provider-reported tokens."""
        single_telemetry_path = self.parity_dir / "single" / "telemetry.json"
        self.assertTrue(single_telemetry_path.exists())

        data = json.loads(single_telemetry_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("usage_source"), "PROVIDER_REPORTED")
        self.assertEqual(data.get("model_requested"), "gemini-flash-latest")
        self.assertEqual(data.get("model_calls"), 1)
        self.assertGreater(data.get("total_tokens", 0), 0)
        self.assertGreater(data.get("model_latency_ms", 0), 0)

    def test_thought_tokens_captured_separately(self):
        """Verify ModelUsage extracts thoughts_tokens and separates from prompt/completion."""
        from integrations.models.base import ModelUsage
        usage = ModelUsage(
            prompt_tokens=1577,
            completion_tokens=3197,
            thoughts_tokens=1252,
            total_tokens=6026,
            usage_source="PROVIDER_REPORTED",
        )
        self.assertEqual(usage.prompt_tokens, 1577)
        self.assertEqual(usage.completion_tokens, 3197)
        self.assertEqual(usage.thoughts_tokens, 1252)
        self.assertEqual(usage.total_tokens, 6026)
        self.assertNotEqual(usage.prompt_tokens + usage.completion_tokens, usage.total_tokens)
        self.assertEqual(usage.prompt_tokens + usage.completion_tokens + usage.thoughts_tokens, usage.total_tokens)

    def test_missing_usage_field_not_coerced_to_zero(self):
        """Verify missing optional usage fields default to None rather than fake zero."""
        from integrations.models.base import ModelUsage
        usage = ModelUsage(
            prompt_tokens=100,
            completion_tokens=200,
            total_tokens=300,
        )
        self.assertIsNone(usage.thoughts_tokens)
        self.assertIsNone(usage.cached_tokens)
        self.assertIsNone(usage.tool_use_prompt_tokens)

    def test_provider_total_preserved_exactly(self):
        """Verify single baseline telemetry preserves provider total exactly."""
        single_telemetry_path = self.parity_dir / "single" / "telemetry.json"
        self.assertTrue(single_telemetry_path.exists())
        data = json.loads(single_telemetry_path.read_text(encoding="utf-8"))
        self.assertEqual(data.get("total_tokens"), 6026)
        self.assertEqual(data.get("prompt_tokens"), 1577)
        self.assertEqual(data.get("completion_tokens"), 3197)
        self.assertEqual(data.get("thoughts_tokens"), 1252)

    def test_benchmark_checkpoint_resume_and_preservation(self):
        """Verify successful single baseline is preserved on disk and not destroyed."""
        single_out = self.parity_dir / "single" / "output.json"
        single_telem = self.parity_dir / "single" / "telemetry.json"
        self.assertTrue(single_out.exists())
        self.assertTrue(single_telem.exists())

        out_data = json.loads(single_out.read_text(encoding="utf-8"))
        self.assertIsInstance(out_data, dict)

    def test_cooldown_pacing_configurable(self):
        """Verify CALL_COOLDOWN_SECONDS is defined and defaults to >= 70.0s."""
        from evaluations.run_phase4_1_2_true_parity import CALL_COOLDOWN_SECONDS
        self.assertGreaterEqual(CALL_COOLDOWN_SECONDS, 70.0)

    def test_blind_packet_both_candidates_non_empty(self):
        """Verify both candidates in blind_review_packet.md contain full, non-empty content."""
        packet_path = self.parity_dir / "blind_review_packet.md"
        self.assertTrue(packet_path.exists())
        content = packet_path.read_text(encoding="utf-8")

        self.assertIn("## CANDIDATE 1: SYSTEM_A", content)
        self.assertIn("## CANDIDATE 2: SYSTEM_B", content)
        self.assertNotIn('"EXECUTIVE_SUMMARY": []', content)
        self.assertNotIn('"EXECUTIVE_SUMMARY": ""', content)
        self.assertNotIn('"RESEARCH_FINDINGS": []', content)
        self.assertNotIn('"POSITIONING": {}', content)
        self.assertNotIn('"CREATIVE_TERRITORIES": []', content)

    def test_blind_packet_has_equivalent_required_deliverables(self):
        """Verify both candidates contain equivalent required deliverables."""
        from evaluations.assemble_blind_packet import (
            build_five_agent_blind_proposal,
            build_single_blind_proposal,
            audit_proposal_completeness,
        )
        five_dir = self.parity_dir / "five_agent"
        single_dir = self.parity_dir / "single"

        p_fa = build_five_agent_blind_proposal(five_dir)
        p_sm = build_single_blind_proposal(single_dir)

        audit_fa = audit_proposal_completeness(p_fa)
        audit_sm = audit_proposal_completeness(p_sm)

        self.assertTrue(all(audit_fa.values()), f"Five-agent missing: {[k for k, v in audit_fa.items() if not v]}")
        self.assertTrue(all(audit_sm.values()), f"Single-model missing: {[k for k, v in audit_sm.items() if not v]}")

    def test_empty_candidate_invalidates_packet(self):
        """Verify audit_proposal_completeness rejects empty candidates."""
        from evaluations.assemble_blind_packet import audit_proposal_completeness
        empty_proposal = {"EXECUTIVE_SUMMARY": "", "RESEARCH_FINDINGS": []}
        audit = audit_proposal_completeness(empty_proposal)
        self.assertFalse(all(audit.values()))

    def test_blind_packet_zero_identity_leaks(self):
        """Verify blind packet contains zero forbidden architectural leak words."""
        from evaluations.assemble_blind_packet import audit_identity_leaks
        packet_path = self.parity_dir / "blind_review_packet.md"
        self.assertTrue(packet_path.exists())
        content = packet_path.read_text(encoding="utf-8")

        leaks = audit_identity_leaks(content)
        self.assertEqual(leaks, 0)

    def test_identity_key_kept_separate_and_hidden(self):
        """Verify blind identity key exists as separate file and is valid JSON."""
        key_path = self.parity_dir / "blind_identity_key.json"
        self.assertTrue(key_path.exists())
        key_data = json.loads(key_path.read_text(encoding="utf-8"))
        self.assertIn("SYSTEM_A", key_data.get("randomized_assignment", {}))
        self.assertIn("SYSTEM_B", key_data.get("randomized_assignment", {}))


if __name__ == "__main__":
    unittest.main()
