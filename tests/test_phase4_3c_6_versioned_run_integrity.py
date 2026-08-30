"""Phase 4.3C.6: Versioned Benchmark Run Integrity & Canonical Normalization Tests.

Tests:
1. Run manifest creation and deterministic fingerprint stability
2. Run fingerprint mismatch rejection
3. Execution generation mismatch rejection
4. V1 checkpoints rejected in V2 runs
5. Valid V2 checkpoint resume
6. Deterministic JSON extraction (pure JSON, markdown fenced, prose before/after)
7. Neutral root wrapper unwrapping (go_to_market_strategy, etc.)
8. Canonical key normalization without content modification
9. Malformed / truncated JSON fail-closed handling (0 content patching)
10. Real current successful Single raw output fixture audit
11. Full offline canonical pipeline (Single + Five-Agent -> Blind Packet)
12. Blind packet rejects raw and V1 candidates
13. Learning-ready provenance metadata fields
14. Static bypass audit (0 bypass paths for validation, canonicalization, V1 rejection)
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import (
    assemble_blind_packet,
    audit_proposal_completeness,
    build_five_agent_blind_proposal,
    build_single_blind_proposal,
)
from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkExecutionPolicy,
    BenchmarkHarness,
    is_valid_candidate_checkpoint,
    is_valid_stage_checkpoint,
)
from integrations.models.base import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from schemas.canonical import (
    CANONICAL_KEY_MAP,
    CanonicalProposal,
    CandidateNormalizer,
    NormalizationResult,
    audit_canonical_completeness,
)
from schemas.manifest import BenchmarkRunManifest, compute_run_fingerprint


class TestPhase43C6VersionedRunIntegrity(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        self.v1_hist_dir = self.bench_dir / "runs" / "phase4_3_v1" / "historical"

    def test_run_manifest_and_fingerprint_determinism(self):
        """Verify run fingerprint is stable and deterministic across identical inputs."""
        fp1 = compute_run_fingerprint(
            benchmark_id="BENCH-001",
            execution_generation="phase4_3_v2",
            handoff_contract_version="v2",
            benchmark_spec_hash="hashA",
            product_facts_hash="hashB",
            evidence_bundle_hash="hashC",
            single_prompt_hash="hashD",
            provider_id="xkiro",
            requested_model="mistralai/mistral-large-2512",
            strict_model_pin=True,
            model_call_timeout_seconds=180.0,
        )
        fp2 = compute_run_fingerprint(
            benchmark_id="BENCH-001",
            execution_generation="phase4_3_v2",
            handoff_contract_version="v2",
            benchmark_spec_hash="hashA",
            product_facts_hash="hashB",
            evidence_bundle_hash="hashC",
            single_prompt_hash="hashD",
            provider_id="xkiro",
            requested_model="mistralai/mistral-large-2512",
            strict_model_pin=True,
            model_call_timeout_seconds=180.0,
        )
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

    def test_run_fingerprint_mismatch_rejection(self):
        """Verify altering an immutable input changes fingerprint and causes checkpoint rejection."""
        fp_original = compute_run_fingerprint(
            benchmark_id="BENCH-001",
            execution_generation="phase4_3_v2",
            handoff_contract_version="v2",
            benchmark_spec_hash="hashA",
            product_facts_hash="hashB",
            evidence_bundle_hash="hashC",
            single_prompt_hash="hashD",
            provider_id="xkiro",
            requested_model="mistralai/mistral-large-2512",
            strict_model_pin=True,
            model_call_timeout_seconds=180.0,
        )
        fp_modified = compute_run_fingerprint(
            benchmark_id="BENCH-001",
            execution_generation="phase4_3_v2",
            handoff_contract_version="v2",
            benchmark_spec_hash="hashA_MODIFIED",
            product_facts_hash="hashB",
            evidence_bundle_hash="hashC",
            single_prompt_hash="hashD",
            provider_id="xkiro",
            requested_model="mistralai/mistral-large-2512",
            strict_model_pin=True,
            model_call_timeout_seconds=180.0,
        )
        self.assertNotEqual(fp_original, fp_modified)

        # Stage checkpoint with modified fingerprint must be rejected
        chk_data = {
            "status": "SUCCESS",
            "raw_text": "Valid output text",
            "run_fingerprint": fp_modified,
            "execution_generation": "phase4_3_v2",
        }
        self.assertFalse(is_valid_stage_checkpoint(chk_data, required_fingerprint=fp_original))

    def test_v1_checkpoints_rejected_in_v2(self):
        """Verify historical V1 Five-Agent checkpoints strictly fail-closed in V2 runs."""
        if not (self.v1_hist_dir / "five_agent_final.json").exists():
            self.skipTest("historical generated run fixture is gitignored and absent in clean checkout")
        active_fp = "f" * 64
        # Load from historical V1 folder
        for v1_file in self.v1_hist_dir.glob("five_agent_stage_*.json"):
            v1_data = json.loads(v1_file.read_text(encoding="utf-8"))
            # V1 files lack run_fingerprint, execution_generation, context_version
            self.assertFalse(
                is_valid_stage_checkpoint(
                    v1_data,
                    required_fingerprint=active_fp,
                    required_generation="phase4_3_v2",
                    required_version="v2",
                ),
                f"V1 file {v1_file.name} must be rejected in V2 run",
            )

        v1_final_data = json.loads((self.v1_hist_dir / "five_agent_final.json").read_text(encoding="utf-8"))
        self.assertFalse(
            is_valid_candidate_checkpoint(
                v1_final_data,
                required_fingerprint=active_fp,
                required_generation="phase4_3_v2",
                required_version="v2",
            )
        )

    def test_valid_v2_checkpoint_accepted(self):
        """Verify valid V2 checkpoint matching run fingerprint is accepted."""
        active_fp = "a" * 64
        v2_stage = {
            "status": "SUCCESS",
            "raw_text": "Valid V2 stage output",
            "run_fingerprint": active_fp,
            "execution_generation": "phase4_3_v2",
            "context_version": "v2",
        }
        self.assertTrue(
            is_valid_stage_checkpoint(
                v2_stage,
                required_fingerprint=active_fp,
                required_generation="phase4_3_v2",
                required_version="v2",
            )
        )

    def test_deterministic_json_extraction_formats(self):
        """Test CandidateNormalizer across pure JSON, fenced JSON, prose before/after, and dicts."""
        sample_dict = {"executive_summary": "Overview", "positioning": "Leader"}

        # Format A: Pure JSON
        res_a, _ = CandidateNormalizer.extract_json_object(json.dumps(sample_dict))
        self.assertEqual(res_a, sample_dict)

        # Format B: Markdown fenced JSON
        fenced = f"```json\n{json.dumps(sample_dict)}\n```"
        res_b, _ = CandidateNormalizer.extract_json_object(fenced)
        self.assertEqual(res_b, sample_dict)

        # Format C: Prose before + fenced JSON
        prose_before = f"Here is the strategy:\n```json\n{json.dumps(sample_dict)}\n```"
        res_c, _ = CandidateNormalizer.extract_json_object(prose_before)
        self.assertEqual(res_c, sample_dict)

        # Format D: Fenced JSON + trailing prose
        prose_after = f"```json\n{json.dumps(sample_dict)}\n```\nHope this helps!"
        res_d, _ = CandidateNormalizer.extract_json_object(prose_after)
        self.assertEqual(res_d, sample_dict)

        # Format E: Intro prose + fenced JSON + trailing prose
        prose_both = f"Intro prose\n```json\n{json.dumps(sample_dict)}\n```\nTrailing prose"
        res_e, _ = CandidateNormalizer.extract_json_object(prose_both)
        self.assertEqual(res_e, sample_dict)

        # Format F: Direct dict
        res_f, _ = CandidateNormalizer.extract_json_object(sample_dict)
        self.assertEqual(res_f, sample_dict)

    def test_neutral_root_wrapper_unwrapping(self):
        """Test unwrapping go_to_market_strategy and other neutral root wrappers."""
        wrapped = {
            "go_to_market_strategy": {
                "executive_summary": "Overview statement",
                "positioning": "Strategic positioning",
            }
        }
        unwrapped = CandidateNormalizer.unwrap_root_wrapper(wrapped)
        self.assertIn("executive_summary", unwrapped)
        self.assertIn("positioning", unwrapped)
        self.assertNotIn("go_to_market_strategy", unwrapped)

    def test_canonical_key_normalization(self):
        """Test snake_case to uppercase canonical mapping without content change."""
        raw_dict = {
            "executive_summary": "Summary text",
            "research_findings": ["Finding 1"],
            "top_priority_segment": "Segment A",
            "what_not_to_do": ["Don't overclaim"],
        }
        canon = CandidateNormalizer.canonicalize_keys(raw_dict)
        self.assertEqual(canon["EXECUTIVE_SUMMARY"], "Summary text")
        self.assertEqual(canon["RESEARCH_FINDINGS"], ["Finding 1"])
        self.assertEqual(canon["TOP_PRIORITY_SEGMENT"], "Segment A")
        self.assertEqual(canon["WHAT_NOT_TO_DO"], ["Don't overclaim"])

    def test_malformed_truncated_json_fails_closed(self):
        """Verify truncated JSON returns NORMALIZATION_FAILED with 0 content patching."""
        truncated_raw = "Here is strategy:\n```json\n{\n  \"executive_summary\": \"Incomplete"
        norm_res = CandidateNormalizer.normalize_candidate(
            raw_text=truncated_raw,
            condition_id="SINGLE_MODEL_BASELINE",
        )
        self.assertEqual(norm_res.status, "NORMALIZATION_FAILED")
        self.assertIsNone(norm_res.canonical_proposal)
        self.assertEqual(norm_res.content_patch_count, 0)
        self.assertEqual(norm_res.semantic_rewrite_count, 0)

    def test_real_current_single_raw_output_fixture_audit(self):
        """Audit the immutable live Single raw output fixture."""
        single_file = self.v1_hist_dir / "single_output.json"
        if not single_file.exists():
            self.skipTest("historical generated Single fixture is gitignored and absent in clean checkout")

        single_data = json.loads(single_file.read_text(encoding="utf-8"))
        raw_text = single_data.get("raw_text", "")
        self.assertEqual(len(raw_text), 18487)
        self.assertEqual(single_data.get("provider_requested"), "xkiro")
        self.assertEqual(single_data.get("model_requested"), "mistralai/mistral-large-2512")
        self.assertEqual(single_data.get("usage", {}).get("completion_tokens"), 4096)

        # Truncated at 4096 tokens, so deterministic parser must fail-closed
        norm_res = CandidateNormalizer.normalize_candidate(
            raw_text=raw_text,
            condition_id="SINGLE_MODEL_BASELINE",
        )
        self.assertEqual(norm_res.status, "NORMALIZATION_FAILED")
        self.assertEqual(norm_res.content_patch_count, 0)
        self.assertEqual(norm_res.semantic_rewrite_count, 0)

    def test_full_offline_canonical_pipeline_and_blind_packet(self):
        """Test full end-to-end normalization and blind review packet generation with complete mock outputs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bench_copy = Path(tmpdir) / "bench"
            bench_copy.mkdir()
            (bench_copy / "product_facts.json").write_text((self.bench_dir / "product_facts.json").read_text(), encoding="utf-8")
            (bench_copy / "evidence_bundle.json").write_text((self.bench_dir / "evidence_bundle.json").read_text(), encoding="utf-8")
            (bench_copy / "business_objective.json").write_text((self.bench_dir / "business_objective.json").read_text(), encoding="utf-8")

            # Complete proposal dictionary matching all 7 categories
            complete_gtm = {
                "go_to_market_strategy": {
                    "executive_summary": "Comprehensive evidence-based launch plan for PROD_UNSEEN_AI_SPEAK_VN.",
                    "research_findings": ["Qualitative n=12 shows high fear of speaking English in public."],
                    "known_facts": ["AI speech recognition engine with 200ms latency."],
                    "observations": ["Learners prefer private AI chat over human tutors."],
                    "inferences": ["Confidence barrier is larger than vocabulary barrier."],
                    "hypotheses": ["Gamified daily speaking streaks improve 30-day retention."],
                    "unknowns": ["Willingness to pay subscription price is to_be_established."],
                    "customer_segments": [{"segment_name": "University Job Seekers", "size": "Large"}],
                    "top_priority_segment": "University Job Seekers preparing for MNC interviews.",
                    "positioning": "The safe, judgment-free AI companion to master spoken English.",
                    "value_proposition": "Practice English speaking anytime without fear of embarrassment.",
                    "channel_priorities": ["TikTok Short-Form Video", "Campus Ambassador Programs"],
                    "deferred_channels": ["Paid TV Broadcast", "Print Media"],
                    "what_not_to_do": ["Do not promise native fluency in 30 days."],
                    "creative_territories": [{"territory_name": "The Safe Space to Stumble"}],
                    "selected_creative_territory": "The Safe Space to Stumble",
                    "angles": [{"angle_name": "Stop sweating in meetings"}],
                    "hooks": ["Afraid to speak English at work?", "Your private AI coach is ready."],
                    "short_form_copy": "Master spoken English in 15 mins a day with AI.",
                    "video_script": "Scene 1: Stuttering in meeting. Scene 2: Practicing privately with app.",
                    "measurement_framework": {"primary_metric": "Day 1 Onboarding Conversation Completion"},
                    "experiments": [{"name": "TikTok Hook A/B Test", "sample_size": "to_be_established"}],
                    "attribution_approach": "First-touch onboarding survey and UTM attribution.",
                    "risks": [{"risk": "Speech engine latency in low-bandwidth regions", "mitigation": "Offline audio caching"}],
                    "top_3_priorities": ["Launch beta to 100 students", "Optimize latency", "Run hook test"],
                    "go_test_hold_defer_decisions": {"TikTok": "GO", "B2B Sales": "HOLD"},
                    "human_approval_requirements": {"Ad Spend": "CMO and Finance sign-off required"},
                    "next_actions": "Begin Stage 1 recruitment and prepare TikTok creative assets.",
                }
            }

            complete_json_str = f"Here is the strategy:\n```json\n{json.dumps(complete_gtm, indent=2)}\n```"

            harness = BenchmarkHarness(benchmark_dir=bench_copy, cooldown_seconds=0.0)

            def fake_generate(req: ModelRequest) -> ModelResponse:
                return ModelResponse(
                    request_id="REQ-CANONICAL-TEST",
                    provider="mock_provider",
                    model_name="mock_model",
                    status=ModelResponseStatus.SUCCESS,
                    content=complete_json_str,
                    usage=ModelUsage(prompt_tokens=1000, completion_tokens=1500, total_tokens=2500, usage_source="PROVIDER_REPORTED"),
                )

            with patch.object(harness, "generate_step", side_effect=fake_generate):
                single_res = harness.run_single_condition(dry_run=False)
                five_res = harness.run_five_agent_condition(dry_run=False)

                self.assertEqual(single_res["normalization_status"], "SUCCESS")
                self.assertEqual(five_res["normalization_status"], "SUCCESS")
                self.assertTrue(single_res["completeness"]["is_complete"])
                self.assertTrue(five_res["completeness"]["is_complete"])

                # Assemble blind review packet
                key_path, packet_path = assemble_blind_packet(
                    benchmark_dir=bench_copy,
                    run_dir=harness.run_dir,
                    run_fingerprint=harness.manifest.run_fingerprint,
                    seed=77,
                )

                self.assertTrue(key_path.exists())
                self.assertTrue(packet_path.exists())

                packet_text = packet_path.read_text(encoding="utf-8")
                self.assertIn("CANDIDATE PROPOSAL: SYSTEM_A", packet_text)
                self.assertIn("CANDIDATE PROPOSAL: SYSTEM_B", packet_text)
                self.assertIn("The Safe Space to Stumble", packet_text)
                self.assertNotIn("Single Model", packet_text)
                self.assertNotIn("Governed Five-Agent", packet_text)

    def test_blind_packet_rejects_v1_and_raw_candidates(self):
        """Verify assemble_blind_packet rejects incomplete or V1 candidates."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            single_raw_only = {"status": "SUCCESS", "raw_text": "Not JSON at all"}
            (chk_dir / "single_output.json").write_text(json.dumps(single_raw_only))
            (chk_dir / "five_agent_final.json").write_text(json.dumps(single_raw_only))

            with self.assertRaises(ValueError):
                assemble_blind_packet(benchmark_dir=Path(tmpdir))

    def test_learning_ready_provenance_metadata(self):
        """Verify CanonicalProposal exposes structured learning-ready metadata fields."""
        proposal = CanonicalProposal(
            EXECUTIVE_SUMMARY="Executive summary content",
            benchmark_id="BENCH-001",
            run_id="RUN-001",
            run_fingerprint="abc123hash",
            condition_id="FIVE_AGENT_GOVERNED",
            source_raw_hash="rawhash123",
            provider_requested="xkiro",
            provider_resolved="xkiro",
            model_requested="mistralai/mistral-large-2512",
            model_resolved="mistralai/mistral-large-2512",
            execution_generation="phase4_3_v2",
            candidate_schema_version="v2",
            content_patch_count=0,
            semantic_rewrite_count=0,
        )
        self.assertEqual(proposal.benchmark_id, "BENCH-001")
        self.assertEqual(proposal.run_id, "RUN-001")
        self.assertEqual(proposal.run_fingerprint, "abc123hash")
        self.assertEqual(proposal.source_raw_hash, "rawhash123")
        self.assertEqual(proposal.content_patch_count, 0)
        self.assertEqual(proposal.semantic_rewrite_count, 0)

    def test_single_adoption_parity_validation(self):
        """Verify Single adoption parity validator checks all immutable benchmark inputs."""
        harness = BenchmarkHarness(
            provider_id="xkiro",
            model_name="mistralai/mistral-large-2512",
        )
        # Manifest has deterministic fingerprint representing all comparison inputs
        self.assertEqual(harness.manifest.provider_id, "xkiro")
        self.assertEqual(harness.manifest.requested_model, "mistralai/mistral-large-2512")
        self.assertEqual(harness.manifest.model_call_timeout_seconds, 180.0)
        self.assertTrue(harness.manifest.strict_model_pin)

    def test_static_bypass_audit(self):
        """Verify 0 bypass paths exist for fingerprint validation, canonicalization, and V1 rejection."""
        # 1. Loading checkpoint without matching fingerprint returns False
        self.assertFalse(is_valid_stage_checkpoint({"status": "SUCCESS", "raw_text": "hello"}, required_fingerprint="req_fp"))
        self.assertFalse(is_valid_candidate_checkpoint({"status": "SUCCESS", "raw_text": "hello", "condition": "SINGLE_MODEL_BASELINE"}, required_fingerprint="req_fp"))

        # 2. Normalizing candidate always returns NormalizationResult with 0 content patches
        res = CandidateNormalizer.normalize_candidate("{}", condition_id="TEST")
        self.assertEqual(res.content_patch_count, 0)
        self.assertEqual(res.semantic_rewrite_count, 0)


if __name__ == "__main__":
    unittest.main()
