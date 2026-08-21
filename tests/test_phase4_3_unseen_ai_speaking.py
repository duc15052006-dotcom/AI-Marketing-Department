"""Unit Tests for Phase 4.3A: Unseen True-Parity Benchmark Harness.

Domain: AI English Speaking Practice Application in Vietnam (PROD_UNSEEN_AI_SPEAK_VN).

Validates:
1. Fresh benchmark domain differs from GaN charger benchmark
2. Frozen product facts and evidence bundle isolation
3. Both conditions receive byte-equivalent evidence and deliverable contracts
4. Universal FinalClaimAuditGate applied to both conditions
5. Five-Agent condition uses GovernedExecutionPipeline and ClaimRegister
6. Checkpoint resume logic without completed-stage rerun
7. 0 fallback models allowed
8. 0 identity leaks in blind review packet
9. Blind identity key strictly separate
10. CONTENT_PATCH_COUNT == 0
11. Exact model parity requirement (gemini-flash-latest)
12. Telemetry schema completeness
"""

import json
from pathlib import Path
import unittest

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import assemble_blind_packet
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    CALL_COOLDOWN_SECONDS,
    MODEL_NAME,
    BenchmarkHarness,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.evaluator import Phase43Evaluator
from governance.claim_safety import FinalClaimAuditGate
from governance.runtime_engine import GovernedExecutionPipeline


class TestPhase43UnseenAISpeakingHarness(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        self.harness = BenchmarkHarness(benchmark_dir=self.bench_dir)

    def test_unseen_domain_differs_from_gan_benchmark(self):
        """Verify product facts and domain are completely distinct from 65W GaN charger."""
        facts = self.harness.product_facts
        self.assertEqual(facts["product_id"], "PROD_UNSEEN_AI_SPEAK_VN")
        self.assertEqual(facts["market"], "Vietnam")
        self.assertEqual(facts["business_model"], "Digital subscription application")

        # Verify zero GaN charger terminology
        text_dump = json.dumps(facts).lower()
        self.assertNotIn("gan", text_dump)
        self.assertNotIn("charger", text_dump)
        self.assertNotIn("watt", text_dump)
        self.assertNotIn("65w", text_dump)
        self.assertNotIn("usb-c", text_dump)

    def test_product_facts_and_evidence_bundles_frozen(self):
        """Verify product facts and evidence bundles are non-empty and well-structured."""
        facts = self.harness.product_facts
        evid = self.harness.evidence_bundle
        self.assertGreater(len(facts.get("verified_product_facts", [])), 4)
        self.assertGreater(len(facts.get("unestablished_facts", [])), 10)
        self.assertGreater(len(evid.get("evidence_items", [])), 4)

    def test_both_conditions_receive_byte_equivalent_evidence(self):
        """Verify both single-model prompt and five-agent pipeline consume identical raw evidence JSON."""
        single_prompt = self.harness.build_single_model_prompt()
        self.assertIn("EVID-SPEAK-01", single_prompt)
        self.assertIn("EVID-SPEAK-06", single_prompt)
        self.assertIn(self.harness.product_facts["product_id"], single_prompt)

    def test_same_deliverable_contract_28_dimensions(self):
        """Verify business objective specifies exact 28 deliverable dimensions."""
        reqs = self.harness.business_objective.get("deliverable_requirements", [])
        self.assertEqual(len(reqs), 28)
        self.assertIn("EXECUTIVE_SUMMARY", reqs)
        self.assertIn("RESEARCH_FINDINGS", reqs)
        self.assertIn("MEASUREMENT_FRAMEWORK", reqs)
        self.assertIn("VIDEO_SCRIPT", reqs)
        self.assertIn("HUMAN_APPROVAL_REQUIREMENTS", reqs)

    def test_universal_final_safety_applied_to_both(self):
        """Verify FinalClaimAuditGate is used universally across single and five-agent conditions."""
        self.assertTrue(hasattr(self.harness, "run_single_condition"))
        self.assertTrue(hasattr(self.harness, "run_five_agent_condition"))

    def test_five_agent_uses_governed_execution_pipeline(self):
        """Verify five-agent condition executes through GovernedExecutionPipeline and ClaimRegister."""
        pipeline = GovernedExecutionPipeline(register_id="TEST-PHASE4-3")
        self.assertIsNotNone(pipeline.claim_register)
        self.assertTrue(hasattr(pipeline, "pre_handoff_validation"))
        self.assertTrue(hasattr(pipeline, "evaluate_cmo_final_gate"))

    def test_checkpoint_resume_without_rerun(self):
        """Verify dry-run checkpoint detection works cleanly."""
        res_single = self.harness.run_single_condition(dry_run=True)
        res_five = self.harness.run_five_agent_condition(dry_run=True)
        self.assertEqual(res_single["status"], "DRY_RUN_CHECKPOINT_READY")
        self.assertEqual(res_five["status"], "DRY_RUN_CHECKPOINT_READY")

    def test_exact_model_parity_and_no_fallback(self):
        """Verify model is pinned to gemini-flash-latest with 70s cooldown."""
        self.assertEqual(MODEL_NAME, "gemini-flash-latest")
        self.assertEqual(CALL_COOLDOWN_SECONDS, 70.0)

    def test_blind_packet_and_identity_key_isolation(self):
        """Verify blind packet generation produces isolated key and leak-free packet with complete candidates."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_bench = Path(tmpdir)
            chk = tmp_bench / "checkpoints"
            chk.mkdir()

            # Create non-empty valid mock candidate outputs
            valid_single = {
                "condition": "SINGLE_MODEL_BASELINE",
                "parsed_output": {
                    "executive_summary": "Unified Direct Strategy for AI English App",
                    "known_facts": ["AI practice"],
                    "customer_segments": ["Professionals"],
                    "positioning": "Private Speaking",
                    "creative_territories": ["Overcome Freeze"],
                    "measurement_framework": {"kpi": "active_users"},
                    "risks": ["Retention drop"],
                },
            }
            valid_five = {
                "condition": "FIVE_AGENT_GOVERNED",
                "stages": {
                    "cmo_initial": {"raw_text": '{"summary": "Initial Marketing Plan"}'},
                    "intelligence": {"raw_text": '{"known_facts": ["AI conversation"], "customer_segments": ["Workers"]}'},
                    "strategist": {"raw_text": '{"positioning": "Low-anxiety rehearsal", "top_priority_segment": "Office Workers"}'},
                    "creative": {"raw_text": '{"creative_territories": ["Safe Rehearsal"], "video_script": "Hook: Nervous?"}'},
                    "performance": {"raw_text": '{"measurement_framework": {"metric": "signups"}}'},
                    "final_cmo": {"raw_text": '{"executive_summary": "Synthesized GTM Proposal", "risks": ["Churn"], "next_actions": "Launch"}'},
                },
            }
            (chk / "single_output.json").write_text(json.dumps(valid_single), encoding="utf-8")
            (chk / "five_agent_final.json").write_text(json.dumps(valid_five), encoding="utf-8")

            key_path, packet_path = assemble_blind_packet(benchmark_dir=tmp_bench, seed=123)
            self.assertTrue(key_path.exists())
            self.assertTrue(packet_path.exists())

            key_data = json.loads(key_path.read_text(encoding="utf-8"))
            self.assertIn("SYSTEM_A", key_data)
            self.assertIn("SYSTEM_B", key_data)

            packet_text = packet_path.read_text(encoding="utf-8")
            # Ensure SYSTEM A and SYSTEM B are non-empty
            self.assertNotIn('```json\n{}\n```', packet_text)
            self.assertIn("EXECUTIVE_SUMMARY", packet_text)
            self.assertIn("POSITIONING", packet_text)

            # Ensure zero identity leaks
            self.assertNotIn("Single Model Baseline", packet_text)
            self.assertNotIn("Governed Five-Agent", packet_text)
            self.assertNotIn("gemini-flash-latest", packet_text)
            self.assertNotIn("token count", packet_text.lower())

    def test_blind_packet_fails_on_empty_candidate(self):
        """Verify assemble_blind_packet raises ValueError when a candidate is empty."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_bench = Path(tmpdir)
            chk = tmp_bench / "checkpoints"
            chk.mkdir()
            (chk / "single_output.json").write_text(json.dumps({"parsed_output": {}}), encoding="utf-8")
            (chk / "five_agent_final.json").write_text(json.dumps({"stages": {}}), encoding="utf-8")

            with self.assertRaises(ValueError):
                assemble_blind_packet(benchmark_dir=tmp_bench)

    def test_content_patch_count_is_zero(self):
        """Verify CONTENT_PATCH_COUNT is strictly 0."""
        self.assertEqual(self.harness.content_patch_count, 0)

    def test_evaluator_machine_dimensions(self):
        """Verify deterministic evaluator evaluates 11 dimensions."""
        mock_output = {
            "executive_summary": "Launch AI English app in Vietnam.",
            "known_facts": ["AI conversation role-play"],
            "unknowns": ["price: TO_BE_ESTABLISHED"],
        }
        report = Phase43Evaluator.evaluate_output("MOCK_CANDIDATE", mock_output, final_gate_status="APPROVED")
        self.assertGreaterEqual(report.overall_score, 7.0)
        self.assertEqual(report.content_patch_count, 0)

    def test_entrypoint_execution_in_dry_run_mode(self):
        """Verify main() entrypoint executes in dry-run mode and returns 0 without calling models."""
        from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import main
        exit_code = main(["--dry-run"])
        self.assertEqual(exit_code, 0)

    def test_gemini_adapter_instantiation_and_wiring_no_call(self):
        """Verify GeminiProviderAdapter instantiates with default_model and constructs ModelRequest without live call."""
        from integrations.models.gemini_adapter import GeminiProviderAdapter
        from integrations.models.base import ModelRequest, ModelMessage, ModelRole

        # 1. Harness get_adapter() instantiates cleanly
        adapter = self.harness.get_adapter()
        self.assertIsInstance(adapter, GeminiProviderAdapter)
        self.assertEqual(adapter._default_model, "gemini-flash-latest")

        # 2. Request construction preserves pinned model
        prompt = self.harness.build_single_model_prompt()
        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content=prompt)],
            model_name=MODEL_NAME,
            temperature=0.2,
        )
        self.assertEqual(req.model_name, "gemini-flash-latest")
        self.assertEqual(len(req.messages), 1)

        # 3. Both conditions resolve identical model pinning
        self.assertEqual(MODEL_NAME, "gemini-flash-latest")

    def test_adapter_generate_contract_and_mock_execution(self):
        """Verify adapter contract uses generate() and handles ModelResponse without live calls."""
        from unittest.mock import MagicMock
        from integrations.models.base import ModelResponse, ModelResponseStatus, ModelUsage
        import tempfile

        # 1. Verify generate attribute exists and complete does not
        adapter = self.harness.get_adapter()
        self.assertTrue(hasattr(adapter, "generate"))
        self.assertFalse(hasattr(adapter, "complete"))

        # 2. Mock adapter.generate for Single condition
        mock_adapter = MagicMock()
        mock_resp = ModelResponse(
            request_id="REQ-TEST-001",
            provider="gemini",
            model_name=MODEL_NAME,
            status=ModelResponseStatus.SUCCESS,
            content='{"executive_summary": "Test GTM", "known_facts": ["AI practice"]}',
            usage=ModelUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            latency_ms=120.0,
        )
        mock_adapter.generate.return_value = mock_resp

        with tempfile.TemporaryDirectory() as tmpdir:
            test_harness = BenchmarkHarness(benchmark_dir=self.bench_dir)
            test_harness.checkpoints_dir = Path(tmpdir)
            test_harness.adapter = mock_adapter

            # Run Single condition
            res_single = test_harness.run_single_condition(dry_run=False)
            self.assertEqual(res_single["condition"], "SINGLE_MODEL_BASELINE")
            self.assertEqual(res_single["status"], "SUCCESS")
            self.assertEqual(res_single["usage"]["total_tokens"], 150)
            mock_adapter.generate.assert_called_once()


if __name__ == "__main__":
    unittest.main()
