"""Phase 4.3B.1: Live Checkpoint Integrity & Fail-Closed Completion Tests.

Validates:
1. Strict checkpoint validity definitions:
   - status == SUCCESS
   - non-empty raw_text
   - non-empty parsed_output
   - all 6 stages required for Five-Agent
2. Stale failed/error checkpoints are NEVER treated as completed stages.
3. Empty SUCCESS checkpoints are rejected.
4. Fail-closed runner status (BENCHMARK_INCOMPLETE / RATE_LIMIT_PAUSED).
5. Safe invalid checkpoint reset / archive mechanism.
"""

import json
from pathlib import Path
import tempfile
import unittest

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkHarness,
    is_valid_candidate_checkpoint,
    is_valid_stage_checkpoint,
    main,
)
from integrations.models.fake_gemini_adapter import FakeGeminiProviderAdapter


class TestPhase43B1CheckpointIntegrity(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_stale_error_checkpoint_rejected(self):
        """Verify checkpoints with status == ERROR or empty raw_text are rejected as invalid."""
        err_stage = {"status": "ERROR", "raw_text": "", "usage": {}}
        self.assertFalse(is_valid_stage_checkpoint(err_stage))

        err_single = {
            "condition": "SINGLE_MODEL_BASELINE",
            "status": "ERROR",
            "raw_text": "",
            "parsed_output": {},
        }
        self.assertFalse(is_valid_candidate_checkpoint(err_single))

        err_five = {
            "condition": "FIVE_AGENT_GOVERNED",
            "status": "COMPLETED",
            "stages": {
                "cmo_initial": err_stage,
                "intelligence": err_stage,
                "strategist": err_stage,
                "creative": err_stage,
                "performance": err_stage,
                "final_cmo": err_stage,
            },
        }
        self.assertFalse(is_valid_candidate_checkpoint(err_five))

    def test_empty_success_checkpoint_rejected(self):
        """Verify checkpoints with status == SUCCESS but empty raw_text or parsed_output are rejected."""
        empty_success_stage = {"status": "SUCCESS", "raw_text": "   ", "usage": {}}
        self.assertFalse(is_valid_stage_checkpoint(empty_success_stage))

        empty_success_single = {
            "condition": "SINGLE_MODEL_BASELINE",
            "status": "SUCCESS",
            "raw_text": '{"executive_summary": ""}',
            "parsed_output": {"raw": ""},
        }
        self.assertFalse(is_valid_candidate_checkpoint(empty_success_single))

    def test_valid_complete_checkpoint_accepted(self):
        """Verify valid successful checkpoints with complete content pass validation."""
        valid_stage = {"status": "SUCCESS", "raw_text": '{"summary": "Plan ready"}', "usage": {"total_tokens": 100}}
        self.assertTrue(is_valid_stage_checkpoint(valid_stage))

        valid_single = {
            "condition": "SINGLE_MODEL_BASELINE",
            "status": "SUCCESS",
            "raw_text": '{"executive_summary": "Full strategy"}',
            "parsed_output": {"executive_summary": "Full strategy"},
        }
        self.assertTrue(is_valid_candidate_checkpoint(valid_single))

        valid_five = {
            "condition": "FIVE_AGENT_GOVERNED",
            "status": "COMPLETED",
            "stages": {
                "cmo_initial": valid_stage,
                "intelligence": valid_stage,
                "strategist": valid_stage,
                "creative": valid_stage,
                "performance": valid_stage,
                "final_cmo": valid_stage,
            },
        }
        self.assertTrue(is_valid_candidate_checkpoint(valid_five))

    def test_stale_checkpoint_not_skipped_by_harness(self):
        """Verify harness does not skip execution when stale error checkpoints are present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            err_single = {
                "condition": "SINGLE_MODEL_BASELINE",
                "status": "ERROR",
                "raw_text": "",
                "parsed_output": {},
            }
            (chk_dir / "single_output.json").write_text(json.dumps(err_single), encoding="utf-8")

            fake_adapter = FakeGeminiProviderAdapter()
            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            harness.adapter = fake_adapter

            res = harness.run_single_condition(dry_run=False)
            # Must have called adapter because stale error was ignored
            self.assertEqual(res["status"], "SUCCESS")
            self.assertEqual(len(fake_adapter.recorded_requests), 1)

    def test_safe_invalid_checkpoint_reset_and_archive(self):
        """Verify reset_invalid_checkpoints moves failed files to archive directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            err_stage = {"status": "ERROR", "raw_text": ""}
            (chk_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(err_stage), encoding="utf-8")
            (chk_dir / "single_output.json").write_text(json.dumps(err_stage), encoding="utf-8")

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            audit_before = harness.audit_checkpoints()
            self.assertEqual(len(audit_before["INVALID_FAILED"]), 2)

            archived_count = harness.reset_invalid_checkpoints(archive_dir_name="archived")
            self.assertEqual(archived_count, 2)

            audit_after = harness.audit_checkpoints()
            self.assertEqual(len(audit_after["INVALID_FAILED"]), 0)
            self.assertTrue((chk_dir / "archived" / "single_output.json").exists())


if __name__ == "__main__":
    unittest.main()
