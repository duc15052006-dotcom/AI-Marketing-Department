"""Phase 4.3C.1: Idempotent Checkpoint Reset & Active Model Display Tests.

Tests:
1. Duplicate-safe archiving when target archive file already exists (creates indexed duplicate).
2. Idempotent reset (consecutive resets are completely safe and return 0).
3. Preserves VALID_SUCCESS checkpoints while archiving INVALID_FAILED checkpoints.
4. Environment variable configuration (BENCHMARK_PROVIDER and BENCHMARK_MODEL).
5. Unknown benchmark provider fails closed with explicit error (no silent Gemini fallback).
6. Active CLI startup display reflects configured provider and model.
"""

from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
    BenchmarkHarness,
    main,
)
from integrations.models.base import ModelMessage, ModelRequest, ModelRole


class TestPhase43C1IdempotentReset(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"

    def test_archive_collision_does_not_crash_and_indexes(self):
        """Verify reset_invalid_checkpoints safely creates indexed copies on collision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            archive_dir = chk_dir / "archive_pre_fix"
            archive_dir.mkdir(parents=True, exist_ok=True)

            # Pre-existing file in archive
            (archive_dir / "five_agent_stage_1_cmo.json").write_text('{"archive": "original"}', encoding="utf-8")

            # New failed file in active checkpoints
            failed_stage = {"status": "ERROR", "raw_text": ""}
            (chk_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(failed_stage), encoding="utf-8")

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            archived_count = harness.reset_invalid_checkpoints()

            self.assertEqual(archived_count, 1)
            # Original archive preserved
            self.assertEqual(json.loads((archive_dir / "five_agent_stage_1_cmo.json").read_text(encoding="utf-8")), {"archive": "original"})
            # New indexed archive created
            self.assertTrue((archive_dir / "five_agent_stage_1_cmo__001.json").exists())
            # Active file removed
            self.assertFalse((chk_dir / "five_agent_stage_1_cmo.json").exists())

    def test_reset_is_idempotent(self):
        """Verify multiple consecutive calls to reset_invalid_checkpoints are safe and return 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            failed_stage = {"status": "ERROR", "raw_text": ""}
            (chk_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(failed_stage), encoding="utf-8")

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)

            # 1st reset
            count1 = harness.reset_invalid_checkpoints()
            self.assertEqual(count1, 1)

            # 2nd reset
            count2 = harness.reset_invalid_checkpoints()
            self.assertEqual(count2, 0)

            # 3rd reset
            count3 = harness.reset_invalid_checkpoints()
            self.assertEqual(count3, 0)

    def test_preserve_valid_success_checkpoint(self):
        """Verify VALID_SUCCESS checkpoints are untouched during reset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            valid_single = {
                "condition": "SINGLE_MODEL_BASELINE",
                "status": "SUCCESS",
                "raw_text": '{"executive_summary": "Valid plan"}',
                "parsed_output": {"executive_summary": "Valid plan"},
            }
            failed_stage = {"status": "ERROR", "raw_text": ""}

            (chk_dir / "single_output.json").write_text(json.dumps(valid_single), encoding="utf-8")
            (chk_dir / "five_agent_stage_1_cmo.json").write_text(json.dumps(failed_stage), encoding="utf-8")

            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, checkpoints_dir=chk_dir, cooldown_seconds=0.0)
            archived = harness.reset_invalid_checkpoints()

            self.assertEqual(archived, 1)
            # Valid checkpoint preserved in active directory
            self.assertTrue((chk_dir / "single_output.json").exists())
            # Failed checkpoint archived
            self.assertFalse((chk_dir / "five_agent_stage_1_cmo.json").exists())

    def test_environment_provider_and_model_resolution(self):
        """Verify BENCHMARK_PROVIDER and BENCHMARK_MODEL environment variables are honored."""
        with patch.dict(os.environ, {"BENCHMARK_PROVIDER": "xkiro", "BENCHMARK_MODEL": "mistralai/mistral-large-2512"}):
            harness = BenchmarkHarness(benchmark_dir=self.bench_dir, cooldown_seconds=0.0)
            self.assertEqual(harness.provider_id, "xkiro")
            self.assertEqual(harness.model_name, "mistralai/mistral-large-2512")

    def test_unknown_benchmark_provider_fails_closed(self):
        """Verify benchmark mode raises explicit configuration error on unknown provider without falling back."""
        harness = BenchmarkHarness(
            benchmark_dir=self.bench_dir,
            provider_id="unknown_unregistered_llm",
            model_name="mystery-model",
            cooldown_seconds=0.0,
        )

        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Hello")])

        with self.assertRaises(ValueError) as ctx:
            harness.generate_step(req)
        self.assertIn("BENCHMARK_CONFIGURATION_ERROR", str(ctx.exception))
        self.assertIn("unknown_unregistered_llm", str(ctx.exception))

    def test_cli_startup_display_reflects_active_provider_and_model(self):
        """Verify main() CLI outputs active configured provider and model."""
        captured_out = StringIO()
        with patch("sys.stdout", captured_out):
            ret = main(["--provider", "xkiro", "--model", "mistralai/mistral-large-2512", "--dry-run"])

        self.assertEqual(ret, 0)
        output = captured_out.getvalue()
        self.assertIn("Provider Pinned: xkiro", output)
        self.assertIn("Model Pinned: mistralai/mistral-large-2512", output)
        self.assertIn("Strict Model Pin: True", output)


if __name__ == "__main__":
    unittest.main()
