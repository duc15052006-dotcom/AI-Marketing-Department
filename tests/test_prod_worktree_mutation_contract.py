"""Contract test for PROD-TEST-EVALUATION-WORKTREE-MUTATION-01.

Proves that targeted evaluation/report-generation test paths use temporary
output and do not mutate the three canonical working-tree evaluation files.
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EVAL_FILES = [
    REPO_ROOT / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking" / "blind_three_way_identity_key.json",
    REPO_ROOT / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking" / "blind_three_way_review_packet.md",
    REPO_ROOT / "evaluations" / "phase4_2_1_claim_safety_report.md",
]


def sha256_of_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class TestWorktreeMutationContract(unittest.TestCase):
    """Contract test: evaluation/report test paths must not mutate tracked evaluation files."""

    def test_assemble_blind_packet_uses_temp_dir(self):
        """assemble_three_way_blind_packet writes to provided dir, not to tracked bench_dir."""
        before_hashes = {p: sha256_of_file(p) for p in EVAL_FILES}

        from evaluations.benchmarks.phase4_3_unseen_ai_speaking.assemble_blind_packet import (
            assemble_three_way_blind_packet,
        )

        sample_prop_a = {"EXECUTIVE_SUMMARY": "Test A", "POSITIONING": "Test"}
        sample_prop_b = {"EXECUTIVE_SUMMARY": "Test B", "POSITIONING": "Test"}
        sample_prop_c = {"EXECUTIVE_SUMMARY": "Test C", "POSITIONING": "Test"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            key_path, packet_path = assemble_three_way_blind_packet(
                sample_prop_a, sample_prop_b, sample_prop_c, Path(tmp_dir), seed=42
            )
            self.assertTrue(key_path.exists())
            self.assertTrue(packet_path.exists())
            self.assertIn(tmp_dir, str(key_path))
            self.assertIn(tmp_dir, str(packet_path))

        after_hashes = {p: sha256_of_file(p) for p in EVAL_FILES}
        for p in EVAL_FILES:
            self.assertEqual(
                before_hashes[p],
                after_hashes[p],
                f"Evaluation file mutated: {p.name}",
            )

    def test_offline_audit_uses_temp_dir(self):
        """run_offline_audit with output_dir writes to temp dir, not to tracked evaluations/."""
        before_hashes = {p: sha256_of_file(p) for p in EVAL_FILES}

        from evaluations.run_phase4_2_1_offline_audit import run_offline_audit

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_offline_audit(output_dir=tmp_dir)
            report = Path(tmp_dir) / "phase4_2_1_claim_safety_report.md"
            self.assertTrue(report.exists())

        after_hashes = {p: sha256_of_file(p) for p in EVAL_FILES}
        for p in EVAL_FILES:
            self.assertEqual(
                before_hashes[p],
                after_hashes[p],
                f"Evaluation file mutated: {p.name}",
            )


if __name__ == "__main__":
    unittest.main()
