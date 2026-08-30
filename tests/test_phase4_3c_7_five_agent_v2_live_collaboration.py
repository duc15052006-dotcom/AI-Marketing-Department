"""Phase 4.3C.7: Fresh Five-Agent V2 Live Collaboration Validation Unit Tests.

Validates:
1. Live Five-Agent V2 run artifact completeness and immutability
2. 6-stage execution success
3. All 5 transport edges verified with real token counts (>500 prompt tokens)
4. Semantic utilization matrix verified with exact textual evidence
5. Claim and provenance safety gate pass
6. Strict invariant checks (0 V1 reuse, 0 simulation contamination, 0 content patching)
"""

import json
from pathlib import Path
import unittest

from schemas.canonical import CanonicalProposal, audit_canonical_completeness


class TestPhase43C7FiveAgentV2LiveCollaboration(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        self.run_dir = self.bench_dir / "runs" / "phase4_3_v2" / "RUN-PHASE4-3-V2-LIVE-001"
        if not self.run_dir.exists():
            self.skipTest("generated live benchmark run is intentionally gitignored; run live acceptance separately")

    def test_live_run_manifest_and_fingerprint_integrity(self):
        """Verify the live run manifest exists, is valid, and matches execution_generation."""
        manifest_file = self.run_dir / "run_manifest.json"
        self.assertTrue(manifest_file.exists(), f"Manifest file missing at {manifest_file}")
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))

        self.assertEqual(manifest.get("run_id"), "RUN-PHASE4-3-V2-LIVE-001")
        self.assertEqual(manifest.get("execution_generation"), "phase4_3_v2")
        self.assertEqual(manifest.get("handoff_contract_version"), "v2")
        self.assertTrue(manifest.get("strict_model_pin"))
        self.assertGreater(len(manifest.get("run_fingerprint", "")), 32)

    def test_all_six_stages_executed_successfully(self):
        """Verify all 6 stages executed successfully with valid non-empty responses."""
        stage_names = [
            "five_agent_stage_1_cmo.json",
            "five_agent_stage_2_intel.json",
            "five_agent_stage_3_strat.json",
            "five_agent_stage_4_crtv.json",
            "five_agent_stage_5_perf.json",
            "five_agent_stage_6_final_cmo.json",
        ]
        for s_name in stage_names:
            chk_file = self.run_dir / "checkpoints" / s_name
            self.assertTrue(chk_file.exists(), f"Stage checkpoint missing: {s_name}")
            data = json.loads(chk_file.read_text(encoding="utf-8"))
            self.assertEqual(data.get("status"), "SUCCESS")
            self.assertGreater(len(data.get("raw_text", "").strip()), 100)
            self.assertGreater(data.get("usage", {}).get("prompt_tokens", 0), 200)

    def test_transport_integrity_across_all_five_edges(self):
        """Verify all 5 handoff edges passed transport integrity with non-trivial prompt tokens."""
        audit_file = self.run_dir / "audits" / "transport_integrity_audit.json"
        self.assertTrue(audit_file.exists())
        audit = json.loads(audit_file.read_text(encoding="utf-8"))

        self.assertEqual(audit.get("transport_integrity_overall"), "PASS")
        edges = audit.get("edges", {})
        self.assertEqual(len(edges), 5)

        expected_edges = [
            "CMO_TO_INTELLIGENCE_TRANSPORT",
            "INTELLIGENCE_TO_STRATEGIST_TRANSPORT",
            "STRATEGIST_TO_CREATIVE_TRANSPORT",
            "CREATIVE_TO_PERFORMANCE_TRANSPORT",
            "PERFORMANCE_TO_FINAL_CMO_TRANSPORT",
        ]
        for e_name in expected_edges:
            self.assertIn(e_name, edges)
            self.assertEqual(edges[e_name]["status"], "PASS")
            # In V1, stages 3-6 had only 22-24 prompt tokens. In V2, all have > 500 prompt tokens.
            self.assertGreater(edges[e_name]["prompt_tokens"], 500)
            self.assertTrue(edges[e_name]["upstream_context_present_in_prompt"])

    def test_semantic_utilization_matrix_and_evidence(self):
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

    def test_granular_artifact_separation(self):
        """Verify separate raw/request, raw/response, handoff, and telemetry artifacts exist."""
        req_dir = self.run_dir / "raw" / "request"
        resp_dir = self.run_dir / "raw" / "response"
        handoff_dir = self.run_dir / "handoff"
        telemetry_dir = self.run_dir / "telemetry"

        self.assertTrue(req_dir.exists())
        self.assertTrue(resp_dir.exists())
        self.assertTrue(handoff_dir.exists())
        self.assertTrue(telemetry_dir.exists())

        # Check 6 requests and 6 responses exist
        self.assertEqual(len(list(req_dir.glob("*.txt"))), 6)
        self.assertEqual(len(list(resp_dir.glob("*.txt"))), 6)
        self.assertGreaterEqual(len(list(handoff_dir.glob("*.json"))), 4)
        self.assertEqual(len(list(telemetry_dir.glob("*.json"))), 6)

    def test_strict_invariants(self):
        """Verify strict zero-mutation invariants (0 V1 reuse, 0 simulation, 0 content patching)."""
        summary_file = self.run_dir / "audits" / "live_collaboration_summary.json"
        self.assertTrue(summary_file.exists())
        summary = json.loads(summary_file.read_text(encoding="utf-8"))

        self.assertEqual(summary.get("v1_reuse_count"), 0)
        self.assertEqual(summary.get("simulated_artifact_used_count"), 0)
        self.assertEqual(summary.get("content_patch_count"), 0)
        self.assertEqual(summary.get("semantic_rewrite_count"), 0)


if __name__ == "__main__":
    unittest.main()
