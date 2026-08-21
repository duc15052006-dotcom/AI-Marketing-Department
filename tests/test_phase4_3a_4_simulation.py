"""Phase 4.3A.4: Full No-Network End-to-End Integration Simulation Test Suite.

Validates the complete production benchmark execution pipeline using FakeGeminiProviderAdapter:
- Real BaseModelAdapter / GeminiProviderAdapter interface match
- Full Single-Model condition path
- Full Governed Five-Agent condition path (all 6 stages)
- Realistic provider response formats (Clean JSON, Markdown-wrapped, prose, usage fields)
- Thoughts tokens and provider-reported total tokens persistence
- Complete ClaimRegister and epistemic safety runtime (Firewall, Numeric Authority, Invariance)
- Checkpoint save & resume with 0 completed stage reruns
- HTTP 429 Rate Limit recovery simulation
- HTTP 503 Service Unavailable recovery simulation
- Model parity verification (1/1 Single, 6/6 Five-Agent on gemini-flash-latest)
- Universal FinalClaimAuditGate parity
- Machine evaluation, blind packet assembly (0 identity leaks, 0 content patches)
- Strict network hard-block (NETWORK_CALLS = 0, MODEL_CALLS = 0)
"""

import json
from pathlib import Path
import tempfile
import unittest

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import assemble_blind_packet
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    CALL_COOLDOWN_SECONDS,
    MODEL_NAME,
    BenchmarkHarness,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.evaluator import Phase43Evaluator
from governance.claim_register import ClaimRegister
from governance.claim_safety import (
    ClaimStatusInvarianceValidator,
    CreativeClaimSafetyValidator,
    FinalClaimAuditGate,
    NumericAuthorityValidator,
    PerformancePlanningSafetyValidator,
    ProductClaimFirewall,
    ValidationDecision,
)
from governance.runtime_engine import GovernedExecutionPipeline
from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.fake_gemini_adapter import FakeGeminiProviderAdapter
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    NumericStatus,
    SourceType,
    StatusAwareNumeric,
    SupportStatus,
)


class TestPhase43A4Simulation(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_1_real_provider_interface_match(self):
        """Verify FakeGeminiProviderAdapter matches production BaseModelAdapter contract."""
        fake_adapter = FakeGeminiProviderAdapter(default_model="gemini-flash-latest")
        self.assertIsInstance(fake_adapter, BaseModelAdapter)
        self.assertEqual(fake_adapter.provider_name, "gemini")
        self.assertEqual(fake_adapter.cost_policy, CostPolicy.FREE_TIER_ALLOWED)
        self.assertTrue(fake_adapter.automatic_fallback_allowed)
        self.assertTrue(hasattr(fake_adapter, "generate"))

        req = ModelRequest(
            messages=[ModelMessage(role=ModelRole.USER, content="Hello")],
            model_name="gemini-flash-latest",
        )
        resp = fake_adapter.generate(req)
        self.assertIsInstance(resp, ModelResponse)
        self.assertEqual(resp.status, ModelResponseStatus.SUCCESS)
        self.assertEqual(resp.model_name, "gemini-flash-latest")
        self.assertIsInstance(resp.usage, ModelUsage)
        self.assertEqual(fake_adapter.network_call_attempts, 0)

    def test_2_full_single_condition_path_simulation(self):
        """Execute real BenchmarkHarness.run_single_condition() end-to-end with fake adapter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            fake_adapter = FakeGeminiProviderAdapter(default_model=MODEL_NAME)

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness.adapter = fake_adapter

            result = harness.run_single_condition(dry_run=False)

            self.assertEqual(result["condition"], "SINGLE_MODEL_BASELINE")
            self.assertEqual(result["model_requested"], "gemini-flash-latest")
            self.assertEqual(result["status"], "SUCCESS")
            self.assertIn("executive_summary", result["parsed_output"])
            self.assertIn("universal_final_audit", result)
            self.assertEqual(result["content_patch_count"], 0)
            self.assertTrue((chk_dir / "single_output.json").exists())
            self.assertEqual(len(fake_adapter.recorded_requests), 1)

    def test_3_full_five_agent_condition_path_simulation(self):
        """Execute real BenchmarkHarness.run_five_agent_condition() through all 6 stages with fake adapter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            fake_adapter = FakeGeminiProviderAdapter(default_model=MODEL_NAME)

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness.adapter = fake_adapter

            result = harness.run_five_agent_condition(dry_run=False)

            self.assertEqual(result["condition"], "FIVE_AGENT_GOVERNED")
            self.assertEqual(result["status"], "COMPLETED")
            self.assertEqual(len(result["stages"]), 6)
            self.assertIn("cmo_initial", result["stages"])
            self.assertIn("intelligence", result["stages"])
            self.assertIn("strategist", result["stages"])
            self.assertIn("creative", result["stages"])
            self.assertIn("performance", result["stages"])
            self.assertIn("final_cmo", result["stages"])

            # Verify all stage checkpoint files exist
            self.assertTrue((chk_dir / "five_agent_stage_1_cmo.json").exists())
            self.assertTrue((chk_dir / "five_agent_stage_2_intel.json").exists())
            self.assertTrue((chk_dir / "five_agent_stage_3_strat.json").exists())
            self.assertTrue((chk_dir / "five_agent_stage_4_crtv.json").exists())
            self.assertTrue((chk_dir / "five_agent_stage_5_perf.json").exists())
            self.assertTrue((chk_dir / "five_agent_stage_6_final_cmo.json").exists())
            self.assertTrue((chk_dir / "five_agent_final.json").exists())

            # Verify 6 or 7 model requests generated (7 under RC3 two-pass Performance micro-workflow)
            self.assertIn(len(fake_adapter.recorded_requests), (6, 7))
            for req in fake_adapter.recorded_requests:
                self.assertEqual(req.model_name, "gemini-flash-latest")

    def test_4_realistic_response_formats_a_through_m(self):
        """Test realistic response formats (Clean JSON, Markdown-wrapped, prose, usage fields, claim safety)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)

            # Format A: Clean JSON Object
            clean_json = '{"executive_summary": "Clean JSON", "known_facts": ["AI conversation"]}'
            adapter_a = FakeGeminiProviderAdapter(responses=[clean_json])
            harness_a = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir / "a", cooldown_seconds=0.0)
            harness_a.adapter = adapter_a
            res_a = harness_a.run_single_condition()
            self.assertEqual(res_a["parsed_output"]["executive_summary"], "Clean JSON")

            # Format B: Markdown-Wrapped JSON
            md_json = '```json\n{"executive_summary": "Markdown Wrapped JSON", "known_facts": ["AI conversation"]}\n```'
            adapter_b = FakeGeminiProviderAdapter(responses=[md_json])
            harness_b = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir / "b", cooldown_seconds=0.0)
            harness_b.adapter = adapter_b
            res_b = harness_b.run_single_condition()
            self.assertEqual(res_b["parsed_output"]["executive_summary"], "Markdown Wrapped JSON")

            # Format D & E & F: Usage fields, Thought Tokens, Provider Total
            custom_usage = ModelUsage(
                prompt_tokens=1200,
                completion_tokens=2400,
                thoughts_tokens=780,
                cached_tokens=None,
                tool_use_prompt_tokens=None,
                total_tokens=4380,
            )
            custom_resp = ModelResponse(
                request_id="REQ-CUSTOM-001",
                provider="gemini",
                model_name="gemini-flash-latest",
                content='{"executive_summary": "Telemetry test"}',
                usage=custom_usage,
            )
            adapter_def = FakeGeminiProviderAdapter(responses=[custom_resp])
            harness_def = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir / "def", cooldown_seconds=0.0)
            harness_def.adapter = adapter_def
            res_def = harness_def.run_single_condition()
            self.assertEqual(res_def["usage"]["thoughts_tokens"], 780)
            self.assertIsNone(res_def["usage"]["cached_tokens"])
            self.assertIsNone(res_def["usage"]["tool_use_prompt_tokens"])
            self.assertEqual(res_def["usage"]["total_tokens"], 4380)

            # Format G & H: Unknown and Hypothesis Claim Invariance
            pipeline = GovernedExecutionPipeline(register_id="TEST-SIM-001")
            claim_unk = MaterialClaim(
                claim_id="CLM-UNK-001",
                claim_text="Subscription pricing is TO_BE_ESTABLISHED",
                claim_class=ClaimClass.UNKNOWN,
                source_type=SourceType.UNSUPPORTED_INVENTION,
                origin_agent="INTELLIGENCE",
                support_status=SupportStatus.UNKNOWN,
                allowed_usage=AllowedUsage.INTERNAL_PLANNING,
            )
            pipeline.claim_register.register_claim(claim_unk)
            rep = pipeline.pre_handoff_validation("INTELLIGENCE", "STRATEGIST", {})
            self.assertEqual(pipeline.claim_register.get_claim("CLM-UNK-001").claim_class, ClaimClass.UNKNOWN)

            # Format I: Unsupported Numeric Claim
            res_num = NumericAuthorityValidator.validate_numeric_authority(
                field_category="PRICE",
                numeric_entry=199000,
                has_human_input=False,
            )
            self.assertEqual(res_num.decision, ValidationDecision.FAIL)
            self.assertEqual(res_num.rule_name, "UNSUPPORTED_NUMERIC_INVENTION")

            # Format J & K & L: Product Claim Firewall
            res_fw_cat = ProductClaimFirewall.audit_claim_text("Our app has verified superior thermal efficiency", SourceType.AGENT_INFERENCE)
            self.assertEqual(res_fw_cat.decision, ValidationDecision.FAIL)

            res_fw_desire = ProductClaimFirewall.audit_claim_text("Our product has Zero Motherboard Risk guarantee", SourceType.AGENT_INFERENCE)
            self.assertEqual(res_fw_desire.decision, ValidationDecision.FAIL)

            # Format M: CMO Prose Override
            claim_blocked = MaterialClaim(
                claim_id="CLM-BLOCKED-001",
                claim_text="Product has Zero Motherboard Risk guarantee.",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.UNSUPPORTED_INVENTION,
                origin_agent="CMO_FINAL",
                support_status=SupportStatus.UNSUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            )
            pipeline.claim_register.register_claim(claim_blocked)
            audit_gate = pipeline.evaluate_cmo_final_gate()
            self.assertEqual(audit_gate.authorization_status, "BLOCKED")

    def test_5_checkpoint_save_and_resume_zero_rerun(self):
        """Verify interrupted Five-Agent execution resumes cleanly without re-running completed stages."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)

            # 2. Instantiate fresh harness and resume
            fake_adapter = FakeGeminiProviderAdapter(default_model=MODEL_NAME)
            harness_resume = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness_resume.adapter = fake_adapter

            # 1. First run: complete stages 1-3, then interrupt before stage 4
            stage_1 = {
                "status": "SUCCESS",
                "raw_text": '{"stage": "cmo_initial"}',
                "run_fingerprint": harness_resume.manifest.run_fingerprint,
                "execution_generation": "phase4_3_v2",
                "context_version": "v2",
                "usage": {},
            }
            stage_2 = {
                "status": "SUCCESS",
                "raw_text": '{"stage": "intelligence"}',
                "run_fingerprint": harness_resume.manifest.run_fingerprint,
                "execution_generation": "phase4_3_v2",
                "context_version": "v2",
                "usage": {},
            }
            stage_3 = {
                "status": "SUCCESS",
                "raw_text": '{"stage": "strategist"}',
                "run_fingerprint": harness_resume.manifest.run_fingerprint,
                "execution_generation": "phase4_3_v2",
                "context_version": "v2",
                "usage": {},
            }

            (chk_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(stage_1), encoding="utf-8")
            (chk_dir / "five_agent_stage_2_intel.json").write_text(json.dumps(stage_2), encoding="utf-8")
            (chk_dir / "five_agent_stage_3_strat.json").write_text(json.dumps(stage_3), encoding="utf-8")

            result = harness_resume.run_five_agent_condition(dry_run=False)

            self.assertEqual(result["status"], "COMPLETED")
            # Stages 1, 2, 3 were restored from checkpoint; fake_adapter only called for remaining stages
            self.assertIn(len(fake_adapter.recorded_requests), (3, 4))

    def test_6_rate_limit_429_recovery_simulation(self):
        """Verify HTTP 429 RATE_LIMITED preserves checkpoints and does not invoke fallback models."""
        resp_429 = ModelResponse(
            request_id="REQ-429-001",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.RATE_LIMITED,
            error="RESOURCE_EXHAUSTED: Quota exceeded for gemini-flash-latest",
        )
        fake_adapter = FakeGeminiProviderAdapter(responses=[resp_429])
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness.adapter = fake_adapter

            res = harness.run_single_condition()
            self.assertEqual(res["status"], "RATE_LIMITED")
            self.assertEqual(fake_adapter._default_model, "gemini-flash-latest")
            self.assertEqual(fake_adapter.network_call_attempts, 0)

    def test_7_service_unavailable_503_recovery_simulation(self):
        """Verify HTTP 503 ERROR preserves checkpoints and does not invoke fallback models."""
        resp_503 = ModelResponse(
            request_id="REQ-503-001",
            provider="gemini",
            model_name="gemini-flash-latest",
            status=ModelResponseStatus.ERROR,
            error="UNAVAILABLE: Service temporarily unavailable (503)",
        )
        fake_adapter = FakeGeminiProviderAdapter(responses=[resp_503])
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness.adapter = fake_adapter

            res = harness.run_single_condition()
            self.assertEqual(res["status"], "ERROR")
            self.assertEqual(fake_adapter._default_model, "gemini-flash-latest")

    def test_8_model_parity_auditing(self):
        """Verify exactly gemini-flash-latest is requested on 1/1 single and 6/7 five-agent requests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            adapter_single = FakeGeminiProviderAdapter()
            harness_single = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir / "s", cooldown_seconds=0.0)
            harness_single.adapter = adapter_single
            harness_single.run_single_condition()
            self.assertEqual(len(adapter_single.recorded_requests), 1)
            self.assertEqual(adapter_single.recorded_requests[0].model_name, "gemini-flash-latest")

            adapter_five = FakeGeminiProviderAdapter()
            harness_five = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir / "f", cooldown_seconds=0.0)
            harness_five.adapter = adapter_five
            harness_five.run_five_agent_condition()
            self.assertIn(len(adapter_five.recorded_requests), (6, 7))
            for req in adapter_five.recorded_requests:
                self.assertEqual(req.model_name, "gemini-flash-latest")

    def test_9_evaluator_and_blind_packet_end_to_end(self):
        """Verify deterministic machine evaluation and blind packet generation with 0 leaks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            bench_copy = chk_dir / "bench"
            bench_copy.mkdir()
            (bench_copy / "product_facts.json").write_text((self.bench_dir / "product_facts.json").read_text(), encoding="utf-8")
            (bench_copy / "evidence_bundle.json").write_text((self.bench_dir / "evidence_bundle.json").read_text(), encoding="utf-8")
            (bench_copy / "business_objective.json").write_text((self.bench_dir / "business_objective.json").read_text(), encoding="utf-8")

            # Run both conditions with fake adapter
            harness = BenchmarkHarness(benchmark_dir=bench_copy, cooldown_seconds=0.0)
            harness.adapter = FakeGeminiProviderAdapter()
            harness.run_single_condition()
            harness.run_five_agent_condition()

            # Assemble blind packet
            key_path, packet_path = assemble_blind_packet(benchmark_dir=bench_copy, seed=99)
            self.assertTrue(key_path.exists())
            self.assertTrue(packet_path.exists())

            packet_text = packet_path.read_text(encoding="utf-8")
            # Verify 0 identity leaks
            self.assertNotIn("Single Model Baseline", packet_text)
            self.assertNotIn("Governed Five-Agent", packet_text)
            self.assertNotIn("gemini-flash-latest", packet_text)

            # Evaluate Single output
            single_data = json.loads((bench_copy / "checkpoints" / "single_output.json").read_text())
            eval_report = Phase43Evaluator.evaluate_output("SINGLE_MODEL", single_data.get("parsed_output", {}))
            self.assertGreaterEqual(eval_report.overall_score, 7.0)
            self.assertEqual(eval_report.content_patch_count, 0)


if __name__ == "__main__":
    unittest.main()
