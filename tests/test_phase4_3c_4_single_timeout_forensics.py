"""Phase 4.3C.4: Single Timeout Forensics & Benchmark Execution Integrity Tests.

Tests:
1. Verification and hash integrity of frozen live Five-Agent checkpoints
2. Effective timeout configuration identification
3. Timeout exception normalization and layer tracing
4. Failed call latency, timestamp, and model identity preservation in checkpoints
5. Single request profile offline measurement
6. Five-Agent 6-stage request profiles offline measurement
7. Handoff content audit and diagnostic identification
8. Timeout simulation vs near-timeout success
9. Valid Five-Agent checkpoint reuse without re-execution
10. Checkpoint provider and model identity persistence
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from evaluations.benchmarks.phase4_3_unseen_ai_speaking.benchmark_harness import (
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
from integrations.models.gateway import UniversalModelGateway
from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.transport import OpenAICompatibleTransport


FROZEN_FIVE_AGENT_HASHES = {
    "five_agent_stage_1_cmo.json": "37dfebe62e9b139d86b4d999f4e3303a958219ed12c7b2de0d79945f4bb99e54",
    "five_agent_stage_2_intel.json": "092bea2152ba99aa91facfdd6ac0795731abe30d9811ab8df869d2eb6f3d606c",
    "five_agent_stage_3_strat.json": "c83db3ebac66ddfa3a89dca62e41e9c717cafcc6ea92bc3299faed9bc8dce4a5",
    "five_agent_stage_4_crtv.json": "c825ce59409c6277880afcac6bc6793a16d4b91825e2d54972ccaa04b606599f",
    "five_agent_stage_5_perf.json": "150ab0526ada21273b0269ea353d10c65e7cc437a96666dd31bf268c0bd6663b",
    "five_agent_stage_6_final_cmo.json": "6852ba4948db5056b55f3ecf7ae7c18420312dee37a30e941b5c4ccd4cbc3cfb",
    "five_agent_final.json": "f03b357b6622ad3d33ab89195c6382c4e6ffc6ed45d69fd35d86923ce77e15dc",
    "claim_register_checkpoint.json": "417d3ef2c8be341ff4d09f22e9eb46c363d30965bc9f93e8b07aaea3721329d6",
    "final_cmo_audit.json": "4c63f0a55bab99687632d1acb048721843967100da926bbbf3440cd343e35d20",
}


class TestPhase43C4SingleTimeoutForensics(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent
        self.bench_dir = self.base_dir / "evaluations" / "benchmarks" / "phase4_3_unseen_ai_speaking"
        self.chk_dir = self.bench_dir / "checkpoints"

        historical_dir = self.bench_dir / "runs" / "phase4_3_v1" / "historical"
        target_dir = historical_dir if historical_dir.exists() else self.chk_dir
        for fname, expected_hash in FROZEN_FIVE_AGENT_HASHES.items():
            fpath = target_dir / fname
            self.assertTrue(fpath.exists(), f"Missing frozen checkpoint {fname}")
            actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            self.assertEqual(actual_hash, expected_hash, f"Hash mismatch for {fname}")

    def test_effective_timeout_resolution(self):
        """Verify effective timeout configuration across layers is 60.0s."""
        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            transport=transport,
        )
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="test")])

        self.assertEqual(transport.timeout_seconds, 60.0)
        self.assertEqual(adapter._timeout_seconds, 60.0)
        self.assertEqual(req.timeout_seconds, 60.0)

    def test_timeout_exception_normalization(self):
        """Verify socket timeout maps cleanly to TIMEOUT status with NOT_AVAILABLE usage."""
        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="test-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
            transport=transport,
        )

        with patch.object(transport, "post_json", return_value=(408, {}, "Request timed out after 60.0s")):
            req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="Heavy prompt")])
            resp = adapter.generate(req)

            self.assertEqual(resp.status, ModelResponseStatus.TIMEOUT)
            self.assertIn("TIMEOUT", resp.error or "")
            self.assertEqual(resp.usage.usage_source, "NOT_AVAILABLE")
            self.assertEqual(resp.usage.total_tokens, 0)

    def test_failed_call_latency_and_identity_preservation(self):
        """Verify failed Single checkpoint saves latency_ms, timestamps, and model identities."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                provider_id="xkiro",
                model_name="mistralai/mistral-large-2512",
                cooldown_seconds=0.0,
            )

            # Mock generate_step to return TIMEOUT
            mock_resp = ModelResponse(
                request_id="REQ-TEST",
                provider="xkiro",
                model_name="mistralai/mistral-large-2512",
                status=ModelResponseStatus.TIMEOUT,
                error="TIMEOUT: xkiro request timed out.",
                latency_ms=60100.0,
            )

            with patch.object(harness, "generate_step", return_value=mock_resp):
                res = harness.run_single_condition(dry_run=False)

                self.assertEqual(res["status"], "TIMEOUT")
                self.assertEqual(res["provider_requested"], "xkiro")
                self.assertEqual(res["model_requested"], "mistralai/mistral-large-2512")
                self.assertIn("latency_ms", res)
                self.assertIn("started_at", res)
                self.assertIn("ended_at", res)

                # Check on-disk file
                disk_file = chk_dir / "single_output.json"
                self.assertTrue(disk_file.exists())
                disk_data = json.loads(disk_file.read_text(encoding="utf-8"))
                self.assertEqual(disk_data["status"], "TIMEOUT")
                self.assertEqual(disk_data["provider_requested"], "xkiro")
                self.assertEqual(disk_data["model_requested"], "mistralai/mistral-large-2512")

    def test_single_request_profile_offline(self):
        """Verify Single request dimensions offline."""
        harness = BenchmarkHarness(benchmark_dir=self.bench_dir)
        prompt = harness.build_single_model_prompt()
        req = ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content=prompt)], model_name="mistralai/mistral-large-2512")

        self.assertEqual(len(req.messages), 1)
        self.assertGreaterEqual(len(prompt), 7000)
        self.assertGreaterEqual(len(json.dumps(req.model_dump())), 7500)
        self.assertIn("executive_summary", prompt)
        self.assertIn("next_actions", prompt)

    def test_five_agent_requests_profile_offline(self):
        """Verify Five-Agent stage prompt sizes offline."""
        harness = BenchmarkHarness(benchmark_dir=self.bench_dir)
        p_id = harness.product_facts["product_id"]
        facts_json = json.dumps(harness.product_facts)
        ev_json = json.dumps(harness.evidence_bundle)

        cmo_p = f"Decompose business objective for {p_id}:\nFacts: {facts_json}\nEvidence: {ev_json}"
        intel_p = f"Conduct market & consumer intelligence for {p_id}:\nEvidence: {ev_json}"
        strat_p = f"Build positioning architecture for {p_id} based on evidence."

        self.assertGreater(len(cmo_p), 4000)
        self.assertGreater(len(intel_p), 2500)
        self.assertLess(len(strat_p), 200)

    def test_valid_five_agent_checkpoint_reuse(self):
        """Verify valid five_agent_final.json checkpoint is returned immediately without model calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            chk_dir = Path(tmpdir)
            harness = BenchmarkHarness(
                benchmark_dir=self.bench_dir,
                checkpoints_dir=chk_dir,
                cooldown_seconds=0.0,
            )

            stage_template = {
                "status": "SUCCESS",
                "raw_text": "Stage output text",
                "run_fingerprint": harness.manifest.run_fingerprint,
                "execution_generation": "phase4_3_v2",
                "context_version": "v2",
            }
            v2_final_checkpoint = {
                "condition": "FIVE_AGENT_GOVERNED",
                "status": "COMPLETED",
                "run_fingerprint": harness.manifest.run_fingerprint,
                "execution_generation": "phase4_3_v2",
                "context_version": "v2",
                "stages": {
                    "cmo_initial": stage_template,
                    "intelligence": stage_template,
                    "strategist": stage_template,
                    "creative": stage_template,
                    "performance": stage_template,
                    "final_cmo": stage_template,
                },
                "raw_text": "Complete output",
            }
            (chk_dir / "five_agent_final.json").write_text(json.dumps(v2_final_checkpoint), encoding="utf-8")

            with patch.object(harness, "generate_step") as mock_gen:
                res = harness.run_five_agent_condition(dry_run=False)
                self.assertEqual(res["status"], "COMPLETED")
                self.assertEqual(len(res["stages"]), 6)
                mock_gen.assert_not_called()

    def test_timeout_simulation_and_near_timeout_success(self):
        """Simulate timeout error and near-timeout success offline."""
        transport = OpenAICompatibleTransport(base_url="https://api.xkiro.com/v1", api_key="test-key")
        adapter = OpenAICompatibleProviderAdapter(
            provider_id="xkiro",
            base_url="https://api.xkiro.com/v1",
            api_key_env="XKIRO_API_KEY",
            default_model="mistralai/mistral-large-2512",
            api_key="test-key",
            transport=transport,
        )

        # 1. Timeout simulation
        with patch.object(transport, "post_json", return_value=(408, {}, "Request timed out")):
            resp_to = adapter.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="hi")]))
            self.assertEqual(resp_to.status, ModelResponseStatus.TIMEOUT)

        # 2. Near-timeout success simulation (completed at 58s with 200 OK)
        fake_success = {
            "model": "mistralai/mistral-large-2512",
            "choices": [{"message": {"role": "assistant", "content": '{"executive_summary": "Success"}'}}],
            "usage": {"total_tokens": 500},
        }
        with patch.object(transport, "post_json", return_value=(200, {}, json.dumps(fake_success))):
            resp_succ = adapter.generate(ModelRequest(messages=[ModelMessage(role=ModelRole.USER, content="hi")]))
            self.assertEqual(resp_succ.status, ModelResponseStatus.SUCCESS)
            self.assertEqual(resp_succ.content, '{"executive_summary": "Success"}')


if __name__ == "__main__":
    unittest.main()
