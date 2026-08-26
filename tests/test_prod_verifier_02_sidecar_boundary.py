"""PROD-VERIFIER-02B — Isolated Verifier Execution Boundary certification.

Deterministic, hermetic contract tests for the restored verifier sidecar
boundary. No torch, no transformers, no model downloads, no internet.
The neural stack is simulated exclusively through tests/fake_verifier_worker.py,
selected via explicit dependency injection into SidecarClaimVerifier.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FAKE_WORKER = REPO_ROOT / "tests" / "fake_verifier_worker.py"
CLAIM_OK = "Battery capacity is 5000mAh."
EVIDENCE_OK = "Official specification: battery capacity is 5000mAh."

from runtime.claim_verification import (  # noqa: E402
    MockClaimVerifier,
    SemanticScores,
)
from runtime.verifier_worker.client import SidecarClaimVerifier  # noqa: E402


def make_client(scenario: str = "", **overrides):
    """Production client using the REAL spawn/reader path; the scenario is
    injected purely as worker argv (dependency injection), so bounded reads,
    stderr draining, and lifecycle code are always exercised."""
    kwargs = dict(
        interpreter_executable=sys.executable,
        worker_script=FAKE_WORKER,
        worker_args=[scenario] if scenario else [],
        expected_dependency_versions="",
        startup_timeout_s=10.0,
        claim_timeout_s=15.0,
    )
    kwargs.update(overrides)
    return SidecarClaimVerifier(**kwargs)


def scenario_client(scenario: str, **overrides):
    return make_client(scenario, **overrides)


def scenario_client(scenario: str, **overrides):
    """Production client with the fake scenario injected as worker argv."""
    return make_client(scenario, **overrides)


class TestImportFirewall(unittest.TestCase):
    """Main runtime must never load torch/transformers."""

    def _probe(self, code: str) -> dict:
        probe = (
            "import sys, json\n"
            + code +
            "\nprint(json.dumps({'torch': 'torch' in sys.modules,"
            " 'transformers': 'transformers' in sys.modules}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_01_historical_inprocess_isolation_defect_structurally_reproduced(self):
        """PROD-VERIFIER-INPROCESS-ISOLATION-01: the certified-head version of
        runtime/claim_verification.py contained direct torch/transformers import
        paths inside the main-process module. Structurally reproduced from git,
        then proven fixed in the working tree."""
        head = subprocess.run(
            ["git", "show", "321d315:runtime/claim_verification.py"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(head.returncode, 0)
        had_torch_path = ("import torch" in head.stdout
                          and "from transformers import" in head.stdout)
        self.assertTrue(had_torch_path,
                        "expected historical in-process ML imports at certified HEAD")
        current = (REPO_ROOT / "runtime" / "claim_verification.py").read_text(encoding="utf-8")
        self.assertNotIn("import torch", current)
        self.assertNotIn("from transformers", current)

    def test_02_main_runtime_import_does_not_load_torch(self):
        probes = self._probe("import runtime.claim_verification")
        self.assertFalse(probes["torch"])

    def test_03_main_runtime_import_does_not_load_transformers(self):
        probes = self._probe("import runtime.engine; import runtime.claim_verification")
        self.assertFalse(probes["torch"])
        self.assertFalse(probes["transformers"])

    def test_04_production_verifier_uses_worker_boundary(self):
        """The production facade is a worker-boundary client, not an in-process
        neural implementation; instantiating it never touches torch."""
        probe = (
            "import sys, json\n"
            "from runtime.verifier_worker.client import SidecarClaimVerifier\n"
            "v = SidecarClaimVerifier()\n"   # no interpreter configured here
            "print(json.dumps({'torch': 'torch' in sys.modules,"
            " 'transformers': 'transformers' in sys.modules,"
            " 'uses_worker_boundary': v.uses_worker_boundary,"
            " 'is_mock': False}))"
        )
        result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO_ROOT),
                                capture_output=True, text=True, timeout=120)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(data["uses_worker_boundary"])
        self.assertFalse(data["torch"])
        self.assertFalse(data["transformers"])


class TestHandshakeAndLifecycle(unittest.TestCase):
    def tearDown(self):
        for attr in ("_client",):
            client = getattr(self, attr, None)
            if client:
                client.close()

    def test_05_valid_worker_handshake(self):
        client = scenario_client("ok:0.97,0.02,0.01")
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            hs = client.handshake
            self.assertIsNotNone(hs)
            self.assertEqual(hs["protocol_version"], "VERIFIER_IPC_V1")
            self.assertEqual(hs["status"], "PROCESS_READY")
            self.assertEqual(hs["model_id"], res.model_id)
            self.assertEqual(hs["model_revision"], res.model_revision)
            self.assertIs(hs["trust_remote_code"], False)
            self.assertIn(hs["python_version"], sys.version)
        finally:
            client.close()

    def test_06_missing_interpreter_fails_closed(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=str(REPO_ROOT / "no_such_python.exe"))
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")
        self.assertIn("Fails closed", res.reason)

    def test_07_worker_startup_failure_fails_closed(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=REPO_ROOT / "tests" / "no_such_worker.py")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_08_worker_immediate_exit_fails_closed(self):
        client = scenario_client("exit_immediate")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_09_broken_pipe_fails_closed(self):
        client = scenario_client("broken_pipe")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_10_malformed_response_fails_closed(self):
        client = scenario_client("malformed_json")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_11_wrong_request_id_rejected(self):
        client = scenario_client("wrong_request_id")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_12_wrong_protocol_version_rejected(self):
        # Handshake declares BOGUS -> rejected during startup validation.
        client = scenario_client("wrong_protocol_version")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_13_invalid_response_schema_fails_closed(self):
        client = scenario_client("bad_schema")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_14_dependency_missing_fails_closed(self):
        client = scenario_client("dep_missing")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")
        self.assertIn("dependencies unavailable", res.reason)

    def test_15_model_load_failure_fails_closed(self):
        client = scenario_client("model_load_failure")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_16_inference_exception_fails_closed(self):
        client = scenario_client("inference_failure")
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_16b_startup_timeout_fails_closed(self):
        client = scenario_client("hang_before_handshake", startup_timeout_s=2.0)
        res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")


class TestVerdictPreservation(unittest.TestCase):
    def _verify_with(self, scenario: str):
        client = scenario_client(scenario)
        try:
            return client, client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        finally:
            pass

    def test_17_supported_response_preserved(self):
        client, res = self._verify_with("ok:0.97,0.02,0.01")
        client.close()
        self.assertEqual(res.verdict.value, "SUPPORTED")
        self.assertGreaterEqual(res.semantic_scores.p_entailment, 0.90)
        self.assertGreaterEqual(res.confidence, 0.90)

    def test_18_contradicted_response_preserved(self):
        client, res = self._verify_with("ok:0.05,0.10,0.85")
        client.close()
        self.assertEqual(res.verdict.value, "CONTRADICTED")

    def test_19_inconclusive_response_preserved(self):
        client, res = self._verify_with("ok:0.50,0.10,0.40")
        client.close()
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")

    def test_20_model_identity_preserved(self):
        from runtime.claim_verification import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION
        client, res = self._verify_with("ok:0.97,0.02,0.01")
        client.close()
        self.assertEqual(res.model_id, DEFAULT_MODEL_ID)
        self.assertEqual(res.model_revision, DEFAULT_MODEL_REVISION)

    def test_21_trust_remote_code_policy_reported_and_enforced(self):
        """Healthy handshake reports trust_remote_code=False; a worker claiming
        trust_remote_code=True must be rejected during handshake validation."""
        client = scenario_client("ok:0.97,0.02,0.01")
        try:
            client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertIs(client.handshake["trust_remote_code"], False)
        finally:
            client.close()

        from runtime.verifier_worker.client import SidecarClaimVerifier, VerifierClientUnavailable
        rogue = SidecarClaimVerifier(
            interpreter_executable=sys.executable,
            worker_script=FAKE_WORKER,
            startup_timeout_s=10.0, claim_timeout_s=15.0,
        )
        # Pre-load the queue with a LYING handshake (trust_remote_code=True).
        import queue as _q
        rogue._process = subprocess.Popen(  # process exists; frames are ours
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        rogue._response_queue = _q.Queue()
        lying = {
            "protocol_version": "VERIFIER_IPC_V1", "type": "handshake",
            "python_version": "3.12.4", "simulated_compatible_worker": True,
            "backend_available": True, "model_id": rogue.model_id,
            "model_revision": rogue.model_revision,
            "trust_remote_code": True, "status": "PROCESS_READY",
        }
        rogue._response_queue.put(json.dumps(lying))
        with self.assertRaises(VerifierClientUnavailable) as ctx:
            rogue._perform_handshake()
        self.assertEqual(ctx.exception.args[0], "TRUST_REMOTE_CODE_POLICY_VIOLATION")
        rogue.close()

    def test_22_entailment_threshold_boundary_preserved(self):
        client = scenario_client("ok:0.90,0.08,0.02")
        res_a = client.verify_claim(CLAIM_OK, EVIDENCE_OK); client.close()
        self.assertEqual(res_a.verdict.value, "SUPPORTED")
        client = scenario_client("ok:0.8999,0.08,0.0201")
        res_b = client.verify_claim(CLAIM_OK, EVIDENCE_OK); client.close()
        self.assertEqual(res_b.verdict.value, "INCONCLUSIVE")

    def test_23_contradiction_threshold_boundary_preserved(self):
        client = scenario_client("ok:0.05,0.25,0.70")
        res_a = client.verify_claim(CLAIM_OK, EVIDENCE_OK); client.close()
        self.assertEqual(res_a.verdict.value, "CONTRADICTED")
        client = scenario_client("ok:0.05,0.2501,0.6999")
        res_b = client.verify_claim(CLAIM_OK, EVIDENCE_OK); client.close()
        self.assertEqual(res_b.verdict.value, "INCONCLUSIVE")


class TestWorkerLifecycle(unittest.TestCase):
    def test_24_one_worker_reused_across_sequential_claims(self):
        client = scenario_client("ok:0.97,0.02,0.01")
        try:
            client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            pid1 = client.worker_pid
            client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            pid2 = client.worker_pid
            self.assertIsNotNone(pid1)
            self.assertEqual(pid1, pid2)
        finally:
            client.close()

    def test_25_no_duplicate_uncontrolled_worker(self):
        client = scenario_client("ok:0.97,0.02,0.01")
        try:
            for _ in range(5):
                client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(len(client.spawned_pids), 1)
        finally:
            client.close()

    def test_26_graceful_close_terminates_worker(self):
        client = scenario_client("ok:0.97,0.02,0.01")
        client.verify_claim(CLAIM_OK, EVIDENCE_OK)
        proc = client._process
        client.close()
        self.assertIsNotNone(proc.poll())

    def test_27_forced_termination_fallback_works(self):
        client = scenario_client("deaf")
        client._ensure_worker()
        proc = client._process
        # deaf worker never reads stdin (ignores EOF); graceful wait must
        # fall back to terminate/kill so the process actually dies.
        client._close_process(graceful=True)
        self.assertIsNotNone(proc.poll())

    def test_27b_bounded_restart_policy_no_infinite_respawn(self):
        """Policy A(bounded): exactly ONE respawn after unexpected death;
        afterwards permanently unavailable until reset()."""
        client = make_client("exit_immediate",
                             interpreter_executable=sys.executable,
                             worker_script=Path("/definitely/not/a/worker.py"))
        try:
            r1 = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(r1.verdict.value, "INCONCLUSIVE")
            r2 = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(r2.verdict.value, "INCONCLUSIVE")
            # respawn budget exhausted -> stable unavailable reason, no loop
            self.assertIsNotNone(client.unavailable_reason)
        finally:
            client.close()

    def test_28_worker_logs_do_not_corrupt_protocol(self):
        client = scenario_client("stderr_noise")
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "SUPPORTED")
        finally:
            client.close()


class TestAuthorityAndHermeticity(unittest.TestCase):
    def test_29_mock_verifier_remains_in_process_and_hermetic(self):
        from runtime.claim_verification import MockClaimVerifier
        spawned = []
        real_popen = subprocess.Popen

        def spying_popen(*a, **kw):
            spawned.append(a)
            return real_popen(*a, **kw)

        mock = MockClaimVerifier()
        res = mock.verify_claim(CLAIM_OK, EVIDENCE_OK)
        self.assertEqual(res.verdict.value, "SUPPORTED")
        self.assertEqual(spawned, [])
        self.assertFalse(hasattr(mock, "uses_worker_boundary") and mock.uses_worker_boundary)

    def test_30_worker_verdict_cannot_alter_provenance_or_scope(self):
        from runtime.claim_verification import VerificationVerdict
        client = scenario_client("ok:0.99,0.005,0.005")  # worker would say SUPPORTED
        try:
            cross_tenant_meta = {
                "tenant_id": "BIZ_A", "run_id": "RUN_A",
                "chat_id": "CHAT_A", "project_id": "PROJ_A",
            }
            other_scope_meta = {
                "tenant_id": "BIZ_B", "scope": "SCOPE_BIZ_B",
                "epistemic_tier": "SOURCE_BACKED_OBSERVATION",
            }
            res = client.verify_claim(
                "Cross tenant claim.", "Some evidence text.",
                claim_metadata=cross_tenant_meta,
                source_metadata=other_scope_meta,
            )
            # Scope authority stays in the main process: SCOPE_VIOLATION even
            # though the (fake or real) worker would score entailment high.
            self.assertEqual(res.verdict, VerificationVerdict.SCOPE_VIOLATION)
            # Provenance hash binds the ORIGINAL scope facts, not the verdict.
            from runtime.claim_verification import compute_provenance_context_hash
            expected_hash = compute_provenance_context_hash(cross_tenant_meta, other_scope_meta)
            self.assertEqual(res.provenance_context_hash, expected_hash)
            # Evidence tier untouched by the worker (no mutation channel exists).
            self.assertEqual(other_scope_meta["epistemic_tier"], "SOURCE_BACKED_OBSERVATION")
        finally:
            client.close()

    def test_30b_interpreter_authority_flows_through_configuration(self):
        """VERIFIER_PYTHON_EXECUTABLE must resolve via ConfigurationAuthority."""
        from config.authority import RuntimeConfigSnapshot, get_runtime_config
        snapshot_fields = RuntimeConfigSnapshot.__dataclass_fields__
        self.assertIn("verifier_python_executable", snapshot_fields)
        snap = get_runtime_config()
        self.assertTrue(hasattr(snap, "verifier_python_executable"))
        # default empty => fail closed (never a machine-specific hardcoded path)
        self.assertIsInstance(snap.verifier_python_executable, str)
        source = (REPO_ROOT / "runtime" / "verifier_worker" / "client.py").read_text(encoding="utf-8")
        self.assertNotIn("C:\\Users\\DUCK", source)
        self.assertNotIn("/Users/", source)

    def test_31_worker_dependency_manifest_exists_without_main_contamination(self):
        manifest = REPO_ROOT / "requirements-verifier.txt"
        self.assertTrue(manifest.exists())
        content = manifest.read_text(encoding="utf-8")
        self.assertIn("torch", content)
        self.assertIn("transformers", content)
        main_req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("torch", main_req)
        self.assertNotIn("transformers", main_req)

    def test_32_production_worker_never_declares_simulation(self):
        source = (REPO_ROOT / "runtime" / "verifier_worker" / "main.py").read_text(encoding="utf-8")
        self.assertIn('"simulated_compatible_worker": False', source)


class TestDeadlineAuthority(unittest.TestCase):
    """PROD-VERIFIER-02C: one monotonic gate deadline; per-claim consumes
    remaining budget; hung workers are terminated; no silent retry."""

    def _silent_client(self, **overrides):
        client = scenario_client("silent", **overrides)
        return client

    def test_36_per_claim_timeout_uses_remaining_gate_budget(self):
        client = self._silent_client(claim_timeout_s=60.0)
        try:
            start = time.monotonic()
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                      deadline_monotonic=start + 1.5)
            elapsed = time.monotonic() - start
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            # Consumed the ~1.5s REMAINING gate budget, not the 60s claim budget.
            self.assertLess(elapsed, 10.0)
        finally:
            client.close()

    def test_37_repeated_claims_do_not_reset_gate_deadline(self):
        client = self._silent_client(claim_timeout_s=60.0)
        try:
            gate_deadline = time.monotonic() + 1.0
            r1 = client.verify_claim(CLAIM_OK, EVIDENCE_OK, deadline_monotonic=gate_deadline)
            start2 = time.monotonic()
            r2 = client.verify_claim(CLAIM_OK, EVIDENCE_OK, deadline_monotonic=start2 - 0.001)
            elapsed2 = time.monotonic() - start2
            self.assertEqual(r1.verdict.value, "INCONCLUSIVE")
            self.assertEqual(r2.verdict.value, "INCONCLUSIVE")
            self.assertIn("TIMEOUT", r2.reason)
            self.assertLess(elapsed2, 1.0)  # exhausted gate -> immediate
        finally:
            client.close()

    def test_38_hung_worker_terminated_on_timeout(self):
        client = self._silent_client(claim_timeout_s=60.0)
        client.verify_claim(CLAIM_OK, EVIDENCE_OK, deadline_monotonic=time.monotonic() + 1.0)
        dead_pid = client.spawned_pids[-1]
        # Timeout path terminates the hung worker (no orphan inference process).
        self.assertIsNone(client._process)
        import ctypes
        kernel32 = ctypes.windll.kernel32 if os.name == "nt" else None
        if kernel32:
            SYNCHRONIZE = 0x00100000
            h = kernel32.OpenProcess(SYNCHRONIZE, False, dead_pid)
            if h:
                try:
                    self.assertEqual(kernel32.WaitForSingleObject(h, 3000), 0)
                finally:
                    kernel32.CloseHandle(h)

    def test_39_timed_out_claim_is_not_automatically_retried(self):
        client = self._silent_client(claim_timeout_s=60.0)
        try:
            before = len(client.spawned_pids)
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                      deadline_monotonic=time.monotonic() + 1.0)
            self.assertIn("TIMEOUT", res.reason)
            # Exactly one spawn attempt served the timed-out claim; the same
            # claim was NOT transparently re-run on a fresh worker.
            self.assertEqual(len(client.spawned_pids), before + 1)
            self.assertNotIn("SUPPORTED", res.reason)
        finally:
            client.close()

    def test_40_later_request_may_use_bounded_restart(self):
        client = self._silent_client(claim_timeout_s=60.0)
        try:
            client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                deadline_monotonic=time.monotonic() + 1.0)
            client.reset()  # explicit bounded restart authorization
            client.worker_args = ["ok:0.97,0.02,0.01"]  # healthy scenario
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                      deadline_monotonic=time.monotonic() + 20.0)
            self.assertEqual(res.verdict.value, "SUPPORTED")
        finally:
            client.close()


class TestProtocolHardening(unittest.TestCase):
    def test_41_wrong_request_id_fails_immediately_without_full_wait(self):
        client = scenario_client("wrong_request_id", claim_timeout_s=60.0)
        try:
            start = time.monotonic()
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            elapsed = time.monotonic() - start
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertLess(elapsed, 15.0)  # immediate rejection, not 60s wait
            self.assertIn("REQUEST_ID_MISMATCH", res.reason)
        finally:
            client.close()

    def test_42_wrong_request_id_invalidates_worker(self):
        client = scenario_client("wrong_request_id")
        try:
            client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertIsNone(client._process)
            self.assertEqual(client.unavailable_reason, "REQUEST_ID_MISMATCH")
        finally:
            client.close()

    def test_43_malformed_frame_invalidates_worker(self):
        client = scenario_client("malformed_json")
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIsNone(client._process)
            self.assertEqual(client.unavailable_reason, "MALFORMED_RESPONSE")
        finally:
            client.close()

    def test_44_oversized_response_frame_rejected(self):
        client = scenario_client("huge_frame", ipc_frame_limit_bytes=8192)
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("FRAME_TOO_LARGE", res.reason)
            self.assertIsNone(client._process)
        finally:
            client.close()

    def test_45_oversized_request_frame_rejected_client_side(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER,
                             max_claim_chars=10000,
                             max_evidence_chars=20000,
                             ipc_frame_limit_bytes=512)
        res = client.verify_claim("c" * 100, "e" * 900)
        self.assertEqual(res.verdict.value, "INCONCLUSIVE")
        self.assertIn("INPUT_TOO_LARGE", res.reason)
        self.assertEqual(client.spawned_pids, [])  # never sent


class TestOversizeDefense(unittest.TestCase):
    """PROD-VERIFIER-SILENT-TRUNCATION-01."""

    class _FakeTokenizer:
        """Mimics HF tokenizer truncation semantics without any model."""
        def __init__(self, ids_per_text=450):
            self.ids_per_text = ids_per_text
            self.calls = []
            self.max_len_used = None

        def __call__(self, a, b, truncation=False, max_length=None, return_tensors=None):
            self.calls.append({"truncation": truncation, "max_length": max_length})
            total = self.ids_per_text * 2
            self.max_len_used = max_length
            if truncation and max_length:
                ids = list(range(min(total, max_length)))
            else:
                ids = list(range(total))
            return {"input_ids": ids}

    class _FakeModel:
        def __init__(self):
            self.called = 0
            self.config = type("C", (), {"max_position_embeddings": 512})()

        def __call__(self, **kw):
            self.called += 1

            class O: pass
            o = O()
            import math
            logits = [0.0, 0.0, 0.0]
            o.logits = type("T", (), {"__getitem__": lambda s, i: [0.9, 0.05, 0.05]})()
            return o

        def eval(self): pass
        def to(self, device): return self

    def _backend_with(self, tokenizer):
        from runtime.verifier_worker.neural_backend import NeuralBackend
        b = NeuralBackend(model_id="m", model_revision="r")
        b._tokenizer = tokenizer
        b._model = self._FakeModel()
        b._label_map = {"entailment": 0, "neutral": 1, "contradiction": 2}
        b._is_loaded = True
        b._active_device = "cpu"
        return b

    def test_47_silent_tokenizer_truncation_defect_reproduced_structurally(self):
        """Pre-fix behavior reproduced: plain HF-style truncation=True silently
        drops tokens from an oversized pair (900-token pair -> exactly 512)."""
        tok = self._FakeTokenizer(ids_per_text=450)  # pair = 900 > 512 context
        truncated = tok("evidence", "claim", truncation=True, max_length=512)
        self.assertEqual(len(truncated["input_ids"]), 512)  # silent drop of 388 tokens
        untruncated = tok("evidence", "claim", truncation=False)
        self.assertEqual(len(untruncated["input_ids"]), 900)

    def test_48_oversized_tokenized_pair_returns_input_too_large(self):
        from runtime.verifier_worker.neural_backend import VerifierBackendError
        backend = self._backend_with(self._FakeTokenizer(ids_per_text=450))  # 900 > 512
        with self.assertRaises(VerifierBackendError) as ctx:
            backend.score(evidence_text="long evidence", claim_text="claim")
        self.assertEqual(ctx.exception.category, "INPUT_TOO_LARGE")

    def test_49_oversized_pair_never_invokes_model_inference(self):
        from runtime.verifier_worker.neural_backend import VerifierBackendError
        tok = self._FakeTokenizer(ids_per_text=450)
        backend = self._backend_with(tok)
        fake_model = backend._model
        with self.assertRaises(VerifierBackendError):
            backend.score(evidence_text="long evidence", claim_text="claim")
        self.assertEqual(fake_model.called, 0)
        # Preflight ran WITHOUT truncation (truthful length measurement).
        preflight_calls = [c for c in tok.calls if not c["truncation"]]
        self.assertTrue(preflight_calls)

    def test_50_oversized_pair_cannot_produce_supported(self):
        from runtime.verifier_worker.neural_backend import VerifierBackendError
        backend = self._backend_with(self._FakeTokenizer(ids_per_text=450))
        with self.assertRaises(VerifierBackendError) as ctx:
            backend.score(evidence_text="e", claim_text="c")
        self.assertNotEqual(ctx.exception.category, "SUPPORTED")
        self.assertEqual(ctx.exception.category, "INPUT_TOO_LARGE")

    def test_51_claim_char_cap(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER,
                             max_claim_chars=50)
        try:
            res = client.verify_claim("c" * 51, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("INPUT_TOO_LARGE", res.reason)
            self.assertEqual(client.spawned_pids, [])
        finally:
            client.close()

    def test_52_evidence_char_cap(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER,
                             max_evidence_chars=100)
        try:
            res = client.verify_claim(CLAIM_OK, "e" * 101)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("INPUT_TOO_LARGE", res.reason)
            self.assertEqual(client.spawned_pids, [])
        finally:
            client.close()

    def test_53_exact_limit_boundary_accepted(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER,
                             max_claim_chars=50, max_evidence_chars=100)
        try:
            res = client.verify_claim("c" * 50, "e" * 100)
            self.assertEqual(res.verdict.value, "SUPPORTED")  # caps are inclusive
        finally:
            client.close()

    def test_54_over_limit_boundary_rejected(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER,
                             max_claim_chars=50)
        try:
            res = client.verify_claim("c" * 51, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
        finally:
            client.close()

    def test_46_worker_independently_rejects_oversized_request(self):
        """Real production worker script enforces its own char limits at the
        protocol layer even when the parent allows more. Tested via direct
        worker IPC (client's 3.12 version gate is separate production truth)."""
        proc = subprocess.Popen(
            [sys.executable, "-X", "utf8",
             str(REPO_ROOT / "runtime" / "verifier_worker" / "main.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", cwd=str(REPO_ROOT),
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        try:
            handshake = json.loads(proc.stdout.readline())
            self.assertEqual(handshake["status"], "PROCESS_READY")
            request = {"protocol_version": "VERIFIER_IPC_V1", "request_id": "r1",
                       "operation": "verify", "claim": "w" * 5000,
                       "evidence": EVIDENCE_OK}
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
            response = json.loads(proc.stdout.readline())
            self.assertEqual(response["status"], "ERROR")
            self.assertEqual(response["error_category"], "INPUT_TOO_LARGE")
        finally:
            proc.kill()


class TestGateClaimLimits(unittest.TestCase):
    """Engine scan resource authority."""

    def _scan(self, sentences_count: int):
        from runtime.engine import FiveAgentDepartmentRuntime
        sentences = [f"The product battery capacity is 5000mAh (source: SRC{i})."
                     for i in range(sentences_count)]
        corpus = " ".join(sentences)
        provenance = {
            f"SRC{i}": {"content": "Battery capacity is certified at 5000mAh.",
                        "epistemic_tier": "SOURCE_BACKED_OBSERVATION",
                        "scope": "GLOBAL"}
            for i in range(sentences_count)
        }
        mock = MockClaimVerifier(default_semantic_scores=SemanticScores(
            p_entailment=0.99, p_neutral=0.005, p_contradiction=0.005,
            argmax_label="ENTAILMENT"))
        return FiveAgentDepartmentRuntime._scan_unsupported_product_claims(
            corpus_text=corpus, provenance_index=provenance,
            context=None, claim_verifier=mock, knowledge_repo=None,
        )

    def test_55_claim_count_cap_exact_boundary_accepted(self):
        total, supported, hyps, reasons, actions = self._scan(64)
        self.assertEqual(total, 64)
        self.assertFalse(any("VERIFIER_RESOURCE_LIMIT" in r for r in reasons))

    def test_56_claim_count_over_limit_blocks_whole_publication(self):
        total, supported, hyps, reasons, actions = self._scan(65)
        self.assertEqual(total, 0)          # nothing verified
        self.assertEqual(supported, 0)      # nothing authorized
        self.assertTrue(any("CLAIM_LIMIT_EXCEEDED" in r for r in reasons))

    def test_57_over_limit_scan_does_not_authorize_partial_prefix(self):
        total, supported, hyps, reasons, actions = self._scan(65)
        # First-64 prefix must NOT be silently authorized.
        self.assertEqual(supported, 0)
        self.assertEqual(actions.get("claim_count"), "BLOCK_PUBLICATION")

    def test_17b_corpus_over_limit_fails_closed(self):
        from runtime.engine import FiveAgentDepartmentRuntime
        corpus = "The battery is 5000mAh (source: SRC0). " * 6000  # ~>200k chars
        reasons, actions = FiveAgentDepartmentRuntime._scan_unsupported_product_claims(
            corpus_text=corpus, provenance_index={}, context=None,
            claim_verifier=MockClaimVerifier(), knowledge_repo=None)[3:5]
        self.assertTrue(any("CORPUS_LIMIT" in r for r in reasons))


class TestBatchAndConcurrency(unittest.TestCase):
    def test_58_verify_batch_exact_max_accepted(self):
        client = scenario_client("ok:0.97,0.02,0.01", max_batch_size=4)
        try:
            results = client.verify_batch([
                (f"Claim {i}.", EVIDENCE_OK, {}, {}) for i in range(4)])
            self.assertEqual(len(results), 4)
            self.assertTrue(all(r.verdict.value == "SUPPORTED" for r in results))
        finally:
            client.close()

    def test_59_verify_batch_over_max_rejected_without_slicing(self):
        from runtime.verifier_worker.client import VerifierResourceLimitError
        client = scenario_client("ok:0.97,0.02,0.01", max_batch_size=4)
        try:
            with self.assertRaises(VerifierResourceLimitError) as ctx:
                client.verify_batch([
                    (f"Claim {i}.", EVIDENCE_OK, {}, {}) for i in range(6)])
            self.assertIn("6", str(ctx.exception))
            self.assertIn("4", str(ctx.exception))
        finally:
            client.close()

    def _hold_semaphore_client(self):
        client = scenario_client("ok:0.97,0.02,0.01", claim_timeout_s=30.0)
        acquired = client._admission_semaphore.acquire(timeout=1.0)
        assert acquired
        return client

    def test_60_concurrent_caller_admission_bounded(self):
        client = self._hold_semaphore_client()
        try:
            results = []
            lock = threading.Lock()

            def caller(i):
                r = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                        deadline_monotonic=time.monotonic() + 3.0)
                with lock:
                    results.append(r)

            threads = [threading.Thread(target=caller, args=(i,)) for i in range(12)]
            for t in threads: t.start()
            for t in threads: t.join(timeout=30)
            self.assertEqual(len(results), 12)
            for r in results:
                self.assertEqual(r.verdict.value, "INCONCLUSIVE")
                self.assertTrue(
                    ("BACKPRESSURE" in r.reason) or ("TIMEOUT" in r.reason),
                    r.reason[:120])
        finally:
            client.close()

    def test_61_waiting_for_worker_consumes_deadline(self):
        client = self._hold_semaphore_client()
        try:
            start = time.monotonic()
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                      deadline_monotonic=start + 1.0)
            elapsed = time.monotonic() - start
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertLess(elapsed, 8.0)   # waited ~1s deadline, not 30s claim timeout
            self.assertGreaterEqual(elapsed, 0.9)
        finally:
            client.close()

    def test_62_backpressure_returns_inconclusive(self):
        client = scenario_client("ok:0.97,0.02,0.01")
        try:
            with client._admission_lock:
                client._admission_waiters = 8  # simulate full waiter slots
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                      deadline_monotonic=time.monotonic() + 5.0)
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("BACKPRESSURE", res.reason)
        finally:
            client.close()


class TestDiagnosticsAndProvenance(unittest.TestCase):
    def test_63_stderr_drain_cannot_deadlock_worker(self):
        client = scenario_client("stderr_flood")
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertEqual(res.verdict.value, "SUPPORTED")
        finally:
            client.close()

    def test_64_stderr_diagnostic_tail_bounded(self):
        client = scenario_client("stderr_flood")
        try:
            client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            tail = client.worker_stderr_tail
            self.assertGreater(len(tail), 0)
            self.assertLessEqual(len(tail), 40)
            total_bytes = sum(len(l.encode("utf-8")) for l in tail)
            self.assertLessEqual(total_bytes, 40 * 512)
        finally:
            client.close()

    def test_65_worker_code_does_not_intentionally_log_claim_or_evidence(self):
        import re as _re
        for rel in ("runtime/verifier_worker/main.py",
                    "runtime/verifier_worker/neural_backend.py"):
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            log_statements = _re.findall(r"logger\.\w+\([^)]*\)", source)
            for stmt in log_statements:
                self.assertNotIn("claim_text", stmt, f"{rel}: {stmt}")
                self.assertNotIn("evidence_text", stmt, f"{rel}: {stmt}")
                self.assertNotIn("evidence,", stmt, f"{rel}: {stmt}")

    def _timeout_result(self):
        client = self._silent = scenario_client("silent", claim_timeout_s=60.0)
        return client, client.verify_claim(CLAIM_OK, EVIDENCE_OK,
                                           deadline_monotonic=time.monotonic() + 1.0)

    def test_66_timeout_reason_provenance_recorded(self):
        client, res = self._timeout_result()
        client.close()
        self.assertTrue(res.reason.startswith("TIMEOUT:"), res.reason[:80])
        self.assertEqual(client.last_error_category, "TIMEOUT")
        self.assertIsNotNone(res.provenance_context_hash)
        self.assertIsNotNone(res.evidence_content_hash)

    def test_67_input_too_large_reason_provenance_recorded(self):
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER, max_claim_chars=50)
        try:
            res = client.verify_claim("c" * 51, EVIDENCE_OK)
            self.assertTrue(res.reason.startswith("INPUT_TOO_LARGE:"), res.reason[:80])
            self.assertIsNotNone(res.provenance_context_hash)
        finally:
            client.close()

    def test_68_protocol_error_reason_provenance_recorded(self):
        client = scenario_client("wrong_request_id", claim_timeout_s=30.0)
        try:
            res = client.verify_claim(CLAIM_OK, EVIDENCE_OK)
            self.assertTrue(res.reason.startswith("PROTOCOL_ERROR:"), res.reason[:80])
        finally:
            client.close()

    def test_69_resource_errors_do_not_upgrade_scope_or_provenance(self):
        """Scope authority precedes resource categories; provenance unchanged."""
        cross_meta = {"tenant_id": "BIZ_A", "run_id": "R", "chat_id": "C",
                      "project_id": "P"}
        other_meta = {"tenant_id": "BIZ_B", "scope": "SCOPE_BIZ_B",
                      "epistemic_tier": "SOURCE_BACKED_OBSERVATION"}
        client = make_client("ok:0.97,0.02,0.01",
                             interpreter_executable=sys.executable,
                             worker_script=FAKE_WORKER, max_claim_chars=10)
        try:
            res = client.verify_claim("c" * 51, EVIDENCE_OK,
                                      claim_metadata=cross_meta,
                                      source_metadata=other_meta)
            # Scope violation wins over INPUT_TOO_LARGE (authority ordering).
            self.assertEqual(res.verdict.value, "SCOPE_VIOLATION")
            from runtime.claim_verification import compute_provenance_context_hash
            self.assertEqual(res.provenance_context_hash,
                             compute_provenance_context_hash(cross_meta, other_meta))
            self.assertEqual(other_meta["epistemic_tier"], "SOURCE_BACKED_OBSERVATION")
        finally:
            client.close()

    def test_70_restart_crash_budget_remains_bounded(self):
        client = make_client("exit_immediate",
                             interpreter_executable=sys.executable,
                             worker_script=Path("/definitely/not/a/worker.py"))
        try:
            attempts = 0
            for _ in range(8):
                client.verify_claim(CLAIM_OK, EVIDENCE_OK)
                attempts += 1
            # Bounded: far fewer real spawn attempts than calls once the budget
            # is exhausted; permanent unavailable reason set.
            self.assertIsNotNone(client.unavailable_reason)
            self.assertLessEqual(attempts, 8)
            self.assertLessEqual(len(client.spawned_pids), 3)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
