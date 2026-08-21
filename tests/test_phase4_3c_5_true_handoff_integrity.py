"""Phase 4.3C.5: True Multi-Agent Handoff Integrity & Uniform Benchmark Timeout Tests.

Tests:
1. CMO -> Intelligence semantic handoff verification
2. Intelligence -> Strategist semantic handoff verification
3. Strategist -> Creative semantic handoff verification
4. Strategy/Creative -> Performance semantic handoff verification
5. All stages -> Final CMO semantic handoff verification
6. Handoff provenance, context version, and source stage references
7. Claim safety and invariance across real structured handoffs
8. Product isolation preservation across handoffs
9. Uniform 180-second benchmark execution timeout policy
10. Full 6-stage real-handoff offline execution simulation with marker verification
11. Final CMO synthesis and FinalClaimAuditGate validation
12. Rejection of defective v1 Five-Agent candidate checkpoints
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkExecutionPolicy,
    BenchmarkHarness,
    is_valid_candidate_checkpoint,
    is_valid_stage_checkpoint,
)
from schemas.claim_provenance import (
    AllowedUsage,
    ClaimClass,
    MaterialClaim,
    SourceType,
    SupportStatus,
)
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from schemas.handoff import HandoffPackage


class TestPhase43C5TrueHandoffIntegrity(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_cmo_to_intelligence_semantic_handoff(self):
        """Verify CMO Initial decomposition and evidence reach Intelligence in structured handoff."""
        harness = BenchmarkHarness(benchmark_dir=self.bench_dir)
        stage_1_data = {
            "status": "SUCCESS",
            "raw_text": "CMO DECOMPOSITION: Focus on working adults in Vietnam needing conversational practice.",
        }

        handoff = HandoffPackage(
            task_id="TASK-INTEL",
            from_agent="CMO_INITIAL",
            to_agent="INTELLIGENCE",
            source_stage_refs=["STAGE_1_CMO:v2"],
            product_id="PROD_UNSEEN_AI_SPEAK_VN",
            brand_id="PROD_UNSEEN_AI_SPEAK_VN",
            objective="Conduct market intelligence",
            product_facts=["Verified Fact 1"],
            verified_evidence_refs=["evidence_bundle"],
            upstream_findings={"cmo_initial_decomposition": stage_1_data["raw_text"]},
            required_next_output="Intelligence report",
        )
        prompt_sec = handoff.format_prompt_section()

        self.assertIn("CMO_INITIAL -> TO: INTELLIGENCE", prompt_sec)
        self.assertIn("STAGE_1_CMO:v2", prompt_sec)
        self.assertIn("working adults in Vietnam", prompt_sec)
        self.assertIn("Verified Fact 1", prompt_sec)

    def test_intelligence_to_strategist_semantic_handoff(self):
        """Verify Intelligence research findings reach Strategist."""
        stage_2_data = {
            "status": "SUCCESS",
            "raw_text": "INTEL FINDINGS: Key competitor lacks real-time pronunciation feedback. High fear of speaking.",
        }

        handoff = HandoffPackage(
            task_id="TASK-STRAT",
            from_agent="INTELLIGENCE",
            to_agent="STRATEGIST",
            source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2"],
            product_id="PROD_UNSEEN_AI_SPEAK_VN",
            brand_id="PROD_UNSEEN_AI_SPEAK_VN",
            objective="Positioning strategy",
            upstream_findings={"intelligence_research_summary": stage_2_data["raw_text"]},
            hypotheses=["Pronunciation feedback drives 2x engagement"],
            required_next_output="Strategy output",
        )
        prompt_sec = handoff.format_prompt_section()

        self.assertIn("INTELLIGENCE -> TO: STRATEGIST", prompt_sec)
        self.assertIn("STAGE_2_INTEL:v2", prompt_sec)
        self.assertIn("lacks real-time pronunciation feedback", prompt_sec)
        self.assertIn("[HYPOTHESIS] Pronunciation feedback drives 2x engagement", prompt_sec)

    def test_strategist_to_creative_semantic_handoff(self):
        """Verify Strategist decisions reach Creative."""
        stage_3_data = {
            "status": "SUCCESS",
            "raw_text": "STRATEGY: Core positioning is 'Safe AI Speaking Companion'. Lead channel is TikTok Short-Form.",
        }

        handoff = HandoffPackage(
            task_id="TASK-CRTV",
            from_agent="STRATEGIST",
            to_agent="CREATIVE",
            source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2", "STAGE_3_STRAT:v2"],
            product_id="PROD_UNSEEN_AI_SPEAK_VN",
            brand_id="PROD_UNSEEN_AI_SPEAK_VN",
            objective="Creative production",
            upstream_decisions={"strategy_positioning_and_channels": stage_3_data["raw_text"]},
            allowed_claims=["AI Speech Analysis", "CEFR Aligned"],
            prohibited_claims=["Guaranteed Fluency in 30 Days"],
            required_next_output="Creative scripts",
        )
        prompt_sec = handoff.format_prompt_section()

        self.assertIn("STRATEGIST -> TO: CREATIVE", prompt_sec)
        self.assertIn("Safe AI Speaking Companion", prompt_sec)
        self.assertIn("TikTok Short-Form", prompt_sec)
        self.assertIn("AI Speech Analysis", prompt_sec)
        self.assertIn("[PROHIBITED] Guaranteed Fluency in 30 Days", prompt_sec)

    def test_context_to_performance_and_final_cmo_handoff(self):
        """Verify Strategy and Creative decisions reach Performance, and all reach Final CMO."""
        stage_3_data = {"raw_text": "STRAT: Channel = TikTok, CAC Target = $5"}
        stage_4_data = {"raw_text": "CRTV: Hook = 'Afraid to speak English at work?'"}

        perf_handoff = HandoffPackage(
            task_id="TASK-PERF",
            from_agent="STRATEGIST_AND_CREATIVE",
            to_agent="PERFORMANCE",
            source_stage_refs=["STAGE_1_CMO:v2", "STAGE_3_STRAT:v2", "STAGE_4_CRTV:v2"],
            product_id="PROD_UNSEEN_AI_SPEAK_VN",
            brand_id="PROD_UNSEEN_AI_SPEAK_VN",
            objective="Performance framework",
            upstream_decisions={
                "strategy_context": stage_3_data["raw_text"],
                "creative_assets": stage_4_data["raw_text"],
            },
            required_next_output="Measurement plan",
        )
        perf_sec = perf_handoff.format_prompt_section()
        self.assertIn("STRATEGIST_AND_CREATIVE -> TO: PERFORMANCE", perf_sec)
        self.assertIn("CAC Target = $5", perf_sec)
        self.assertIn("Afraid to speak English at work?", perf_sec)

        cmo_handoff = HandoffPackage(
            task_id="TASK-CMO-FINAL",
            from_agent="ALL_SPECIALIZED_AGENTS",
            to_agent="CMO_FINAL",
            source_stage_refs=["STAGE_1_CMO:v2", "STAGE_2_INTEL:v2", "STAGE_3_STRAT:v2", "STAGE_4_CRTV:v2", "STAGE_5_PERF:v2"],
            product_id="PROD_UNSEEN_AI_SPEAK_VN",
            brand_id="PROD_UNSEEN_AI_SPEAK_VN",
            objective="Final GTM synthesis",
            upstream_decisions={
                "strategy": stage_3_data["raw_text"],
                "creative": stage_4_data["raw_text"],
                "performance": "PERF: Experiment EXP-001 with 10k sample",
            },
            contradictions=[{"topic": "Audience", "note": "Intel says B2B vs Strat says B2C"}],
            required_next_output="Final JSON GTM Proposal",
        )
        cmo_sec = cmo_handoff.format_prompt_section()
        self.assertIn("ALL_SPECIALIZED_AGENTS -> TO: CMO_FINAL", cmo_sec)
        self.assertIn("EXP-001", cmo_sec)
        self.assertIn("Intel says B2B vs Strat says B2C", cmo_sec)

    def test_uniform_180s_timeout_and_single_source_policy(self):
        """Verify BenchmarkExecutionPolicy enforces 180s timeout across all conditions."""
        policy = BenchmarkExecutionPolicy()
        self.assertEqual(policy.model_call_timeout_seconds, 180.0)
        self.assertTrue(policy.strict_model_pin)
        self.assertFalse(policy.fallback_allowed)

        harness = BenchmarkHarness(benchmark_dir=self.bench_dir, policy=policy)
        self.assertEqual(harness.policy.model_call_timeout_seconds, 180.0)

    def test_rejection_of_defective_v1_checkpoints(self):
        """Verify old v1 Five-Agent checkpoints (missing context_version='v2') are rejected in v2 runs."""
        old_v1_stage = {
            "status": "SUCCESS",
            "raw_text": "Old output without v2 handoff",
            "usage": {"total_tokens": 100},
            # Missing context_version: "v2"
        }
        self.assertFalse(is_valid_stage_checkpoint(old_v1_stage, required_version="v2"))

        v2_stage = {
            "status": "SUCCESS",
            "raw_text": "New output with v2 handoff",
            "context_version": "v2",
            "source_stage_refs": ["STAGE_1_CMO:v2"],
            "usage": {"total_tokens": 100},
        }
        self.assertTrue(is_valid_stage_checkpoint(v2_stage, required_version="v2"))

    def test_full_real_handoff_offline_simulation(self):
        """Simulate all 6 stages with marker tracking through the harness."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                cooldown_seconds=0.0,
            )

            prompts_received = []

            def fake_generate(req: ModelRequest) -> ModelResponse:
                prompt_content = req.messages[0].content
                prompts_received.append(prompt_content)
                stage_idx = len(prompts_received)

                self.assertEqual(req.timeout_seconds, 180.0)

                return ModelResponse(
                    request_id=f"REQ-{stage_idx}",
                    provider="mock_provider",
                    model_name="mock_model",
                    status=ModelResponseStatus.SUCCESS,
                    content=f"STAGE_{stage_idx}_OUTPUT_MARKER with valid deliverables",
                    usage=ModelUsage(prompt_tokens=500, completion_tokens=200, total_tokens=700, usage_source="PROVIDER_REPORTED"),
                )

            with patch.object(harness, "generate_step", side_effect=fake_generate):
                res = harness.run_five_agent_condition(dry_run=False)

                self.assertEqual(res["status"], "COMPLETED")
                self.assertEqual(len(res["stages"]), 6)
                self.assertIn(len(prompts_received), (6, 7))

                # Verify Stage 2 prompt contains Stage 1 marker
                self.assertIn("STAGE_1_OUTPUT_MARKER", prompts_received[1])
                # Verify Stage 3 prompt contains Stage 2 marker
                self.assertIn("STAGE_2_OUTPUT_MARKER", prompts_received[2])
                # Verify Stage 4 prompt contains Stage 3 marker
                self.assertIn("STAGE_3_OUTPUT_MARKER", prompts_received[3])
                # Verify Stage 5 prompt contains Stage 3 & 4 markers
                self.assertIn("STAGE_3_OUTPUT_MARKER", prompts_received[4])
                self.assertIn("STAGE_4_OUTPUT_MARKER", prompts_received[4])
                # Verify Stage 6 prompt (last prompt) contains all stage markers
                self.assertIn("STAGE_1_OUTPUT_MARKER", prompts_received[-1])
                self.assertIn("STAGE_2_OUTPUT_MARKER", prompts_received[-1])
                self.assertIn("STAGE_3_OUTPUT_MARKER", prompts_received[-1])
                self.assertIn("STAGE_4_OUTPUT_MARKER", prompts_received[-1])
                self.assertIn("STAGE_5_OUTPUT_MARKER", prompts_received[-1])

    def test_claim_safety_and_invariance_across_handoffs(self):
        """Verify claim status invariance and firewall operate during structured handoffs."""
        from governance.runtime_engine import GovernedExecutionPipeline

        pipeline = GovernedExecutionPipeline(register_id="TEST-REG-001")
        pipeline.claim_register.register_claim(
            MaterialClaim(
                claim_id="CLM-TEST-001",
                claim_text="Verified AI speech analysis",
                claim_class=ClaimClass.VERIFIED_PRODUCT_FACT,
                source_type=SourceType.INPUT_SPEC,
                origin_agent="INPUT_SPEC",
                support_status=SupportStatus.SUPPORTED,
                allowed_usage=AllowedUsage.PUBLIC_CLAIM,
            )
        )

        stage_1_data = {
            "status": "SUCCESS",
            "raw_text": "CMO output with valid claim",
        }
        report = pipeline.pre_handoff_validation("CMO_INITIAL", "INTELLIGENCE", stage_1_data)
        self.assertTrue(report.is_valid)

    def test_product_isolation_preserved_across_handoffs(self):
        """Verify product_id and brand_id are strictly preserved in all handoff packages."""
        h1 = HandoffPackage(
            task_id="TASK-1",
            from_agent="A",
            to_agent="B",
            product_id="PROD_ISOLATED_001",
            brand_id="BRAND_ISOLATED_001",
            objective="Isolation test",
            required_next_output="Out",
        )
        sec = h1.format_prompt_section()
        self.assertIn("TARGET PRODUCT: PROD_ISOLATED_001 (Brand: BRAND_ISOLATED_001)", sec)

    def test_final_cmo_synthesis_and_gate(self):
        """Verify Final CMO receives structured handoff and FinalClaimAuditGate evaluates register."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                cooldown_seconds=0.0,
            )

            def fake_generate(req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id="REQ-TEST",
                    provider="mock_provider",
                    model_name="mock_model",
                    status=ModelResponseStatus.SUCCESS,
                    content='{"executive_summary": "Comprehensive GTM plan synthesized across all agents"}',
                    usage=ModelUsage(prompt_tokens=500, completion_tokens=200, total_tokens=700, usage_source="PROVIDER_REPORTED"),
                )

            with patch.object(harness, "generate_step", side_effect=fake_generate):
                res = harness.run_five_agent_condition(dry_run=False)
                self.assertEqual(res["status"], "COMPLETED")
                self.assertIn("universal_final_audit", res)
                self.assertEqual(res["universal_final_audit"]["authorization_status"], "APPROVED")


if __name__ == "__main__":
    unittest.main()
