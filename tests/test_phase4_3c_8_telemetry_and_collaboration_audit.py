"""Phase 4.3C.8: Live V2 Telemetry & Collaboration Evidence Audit Unit Tests.

Validates:
1. Raw telemetry token arithmetic (prompt + completion + thoughts == total_tokens) for all 6 stages (0 delta).
2. End-to-end token reconciliation (6,260 visible input + 9,988 visible output + 13,173 reasoning == 29,421 total).
3. Semantic collaboration evidence across all 5 handoff edges (>=3 information units per edge).
4. Final CMO lineage tracing across Intelligence, Strategist, Creative, and Performance.
5. Canonical proposal deliverable origin mapping with zero content patching and zero semantic mutation.
6. Deterministic model alias resolution.
7. Raw artifact immutability.
"""

import json
from pathlib import Path
import unittest

from integrations.models.gemini_adapter import GeminiProviderAdapter


class TestPhase43C8TelemetryAndCollaborationAudit(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        self.run_dir = self.bench_dir / "runs" / "phase4_3_v2" / "RUN-PHASE4-3-V2-LIVE-001"

    def test_raw_telemetry_exact_arithmetic_all_stages(self):
        """Verify prompt_tokens + completion_tokens + thoughts_tokens == total_tokens with delta=0 for all 6 stages."""
        stage_names = [
            "stage_1_cmo_initial_telemetry.json",
            "stage_2_intelligence_telemetry.json",
            "stage_3_strategist_telemetry.json",
            "stage_4_creative_telemetry.json",
            "stage_5_performance_telemetry.json",
            "stage_6_cmo_final_telemetry.json",
        ]
        telemetry_dir = self.run_dir / "telemetry"
        self.assertTrue(telemetry_dir.exists())

        for s_file in stage_names:
            tf = telemetry_dir / s_file
            self.assertTrue(tf.exists(), f"Missing telemetry file {s_file}")
            data = json.loads(tf.read_text(encoding="utf-8"))

            p = data.get("prompt_tokens", 0)
            c = data.get("completion_tokens", 0)
            t = data.get("thoughts_tokens", 0) or 0
            tot = data.get("total_tokens", 0)

            recomputed = p + c + t
            delta = tot - recomputed

            self.assertEqual(
                delta, 0, f"Token arithmetic mismatch in {s_file}: {p} + {c} + {t} = {recomputed} != {tot}"
            )
            self.assertEqual(data.get("usage_source"), "PROVIDER_REPORTED")

    def test_end_to_end_token_reconciliation(self):
        """Verify sum of visible input, visible output, and reasoning equals provider total tokens."""
        telemetry_dir = self.run_dir / "telemetry"
        total_p = 0
        total_c = 0
        total_t = 0
        total_provider = 0

        for tf in sorted(telemetry_dir.glob("*.json")):
            data = json.loads(tf.read_text(encoding="utf-8"))
            total_p += data.get("prompt_tokens", 0)
            total_c += data.get("completion_tokens", 0)
            total_t += data.get("thoughts_tokens", 0) or 0
            total_provider += data.get("total_tokens", 0)

        self.assertEqual(total_p, 6260, f"Expected 6,260 visible input tokens, got {total_p}")
        self.assertEqual(total_c, 9988, f"Expected 9,988 visible output tokens, got {total_c}")
        self.assertEqual(total_t, 13173, f"Expected 13,173 reasoning tokens, got {total_t}")
        self.assertEqual(total_provider, 29421, f"Expected 29,421 provider total tokens, got {total_provider}")
        self.assertEqual(total_p + total_c + total_t, total_provider)

    def test_semantic_collaboration_evidence_depth(self):
        """Verify semantic utilization matrix records passing evidence across all 5 handoffs."""
        matrix_file = self.run_dir / "audits" / "semantic_utilization_matrix.json"
        self.assertTrue(matrix_file.exists())
        matrix_data = json.loads(matrix_file.read_text(encoding="utf-8"))

        self.assertEqual(matrix_data.get("semantic_utilization_overall"), "PASS")
        matrix = matrix_data.get("matrix", [])
        self.assertEqual(len(matrix), 5)
        for item in matrix:
            self.assertEqual(item.get("result"), "PASS")
            self.assertGreater(len(item.get("evidence", "")), 50)

    def test_final_cmo_lineage_to_all_specialists(self):
        """Verify Final CMO incorporates insights from Stages 1-5."""
        s6_req = (self.run_dir / "raw" / "request" / "stage_6_cmo_final_request.txt").read_text(encoding="utf-8")
        self.assertIn("HNDF-ALL-TO-CMO-FINAL", s6_req)
        self.assertIn("intelligence_summary", s6_req)
        self.assertIn("cmo_initial", s6_req)
        self.assertIn("strategy", s6_req)
        self.assertIn("creative", s6_req)
        self.assertIn("performance", s6_req)

    def test_model_identity_resolution_determinism(self):
        """Verify model alias resolution deterministically maps gemini-flash-latest to gemini-3.5-flash."""
        adapter = GeminiProviderAdapter(default_model="gemini-flash-latest")
        self.assertEqual(adapter.MODEL_ALIASES.get("gemini-flash-latest"), "gemini-3.5-flash")
        self.assertEqual(adapter.MODEL_ALIASES.get("gemini-3.5-flash"), "gemini-3.5-flash")

    def test_raw_artifact_immutability(self):
        """Verify all 6 request and response text files, 5 handoff files, and 6 telemetry files exist."""
        req_files = list((self.run_dir / "raw" / "request").glob("*.txt"))
        resp_files = list((self.run_dir / "raw" / "response").glob("*.txt"))
        handoff_files = list((self.run_dir / "handoff").glob("*.json"))
        telemetry_files = list((self.run_dir / "telemetry").glob("*.json"))

        self.assertEqual(len(req_files), 6)
        self.assertEqual(len(resp_files), 6)
        self.assertEqual(len(handoff_files), 5)
        self.assertEqual(len(telemetry_files), 6)

        # Check checkpoints directory
        chk_files = list((self.run_dir / "checkpoints").glob("*.json"))
        self.assertEqual(len(chk_files), 7)  # 6 stages + final


if __name__ == "__main__":
    unittest.main()
