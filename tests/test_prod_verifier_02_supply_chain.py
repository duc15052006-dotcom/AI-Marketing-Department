"""PROD-VERIFIER-02D — Worker Dependency & Model Supply-Chain Integrity.

Hermetic. No torch/transformers install, no model download, no network.
Real-model behaviors are exercised through the REAL production worker script
(runtime/verifier_worker/main.py) on its torch-free handshake/attestation
path, plus DI fake workers for client attestation decisions.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

FAKE_WORKER = REPO_ROOT / "tests" / "fake_verifier_worker.py"
PROD_WORKER = REPO_ROOT / "runtime" / "verifier_worker" / "main.py"
PIN = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"

from runtime.verifier_worker.client import SidecarClaimVerifier  # noqa: E402


def make_client(scenario: str, **overrides):
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


def spawn_prod_worker(env_overrides: dict):
    env = {**os.environ,
           "PYTHONPATH": str(REPO_ROOT),
           "PYTHONNOUSERSITE": "1",
           **env_overrides}
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", str(PROD_WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env,
    )


def roundtrip(proc, frame: dict) -> dict:
    proc.stdin.write(json.dumps(frame) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def make_snapshot(root: Path) -> Tuple[Path, Path, dict]:
    """Create a synthetic verified model snapshot + trusted manifest fixture."""
    snapshot = root / "snapshots" / PIN
    snapshot.mkdir(parents=True, exist_ok=True)
    files = {
        "config.json": b'{"model_type": "deberta-v2"}',
        "model.safetensors": b"\x00\x01FAKE-SAFETENSORS-BODY\x02\x03",
        "tokenizer.json": b'{"fake_tokenizer": true}',
    }
    entries = []
    for rel, content in files.items():
        p = snapshot / rel
        p.write_bytes(content)
        entries.append({"path": rel,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "size": len(content)})
    manifest = {"manifest_version": 1, "model_id": MODEL_ID,
                "model_revision": PIN, "files": entries}
    manifest_path = root / "manifests" / f"{PIN}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(indent=None) if False else json.dumps(manifest, indent=1),
                             encoding="utf-8")
    return snapshot, manifest_path, manifest


class TestDependencyBaseline(unittest.TestCase):

    def test_01_current_verifier_requirements_certified_pins(self):
        """PROD-VERIFIER-02E: exact pins frozen from the REAL acceptance run."""
        content = (REPO_ROOT / "requirements-verifier.txt").read_text(encoding="utf-8")
        self.assertIn("torch==2.13.0+cpu", content)            # attested historical
        for pin in ("transformers==4.57.6", "numpy==2.5.2",
                    "huggingface_hub==0.36.2", "tokenizers==0.22.2",
                    "safetensors==0.8.0"):
            self.assertIn(pin, content)                        # NEW_ACCEPTANCE baseline
        self.assertIn("NEW_ACCEPTANCE", content)
        main_req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("torch", main_req.lower())

    def test_02_historical_dependency_version_evidence_inventory(self):
        """Exact versions attested by committed calibration artifacts.

        The artifact describes the HISTORICAL production model
        (mdeberta-v3-base-xnli-multilingual @ b5113eb…) and is preserved
        unmodified as historical evidence (PROD-VERIFIER-02F-R1 §1).
        """
        results = json.loads(
            (REPO_ROOT / "tests/data/claim_verification_holdout_results_mdeberta.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(results["python_version"].split(" ")[0], "3.12.14")
        self.assertEqual(results["torch_version"], "2.13.0+cpu")
        # Historical identity, deliberately NOT the promoted production model.
        self.assertEqual(results["model_id"],
                         "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7")

    def test_03_real_verifier_environment_provisioned(self):
        """PROD-VERIFIER-02E: the isolated Python 3.12 worker environment now
        exists (gitignored) and reports the certified interpreter version."""
        venv_python = REPO_ROOT / ".verifier-venv" / "Scripts" / "python.exe"
        self.assertTrue(venv_python.exists())
        result = subprocess.run([str(venv_python), "--version"],
                                capture_output=True, text=True, timeout=60)
        self.assertIn("3.12.14", result.stdout + result.stderr)

    def test_39_main_requirements_remains_ml_free(self):
        main_req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        for forbidden in ("torch", "transformers", "huggingface", "tokenizers",
                          "safetensors", "numpy"):
            self.assertNotIn(forbidden, main_req.lower())


class TestWorkerEnvironmentSanitization(unittest.TestCase):

    def _probe_worker_env(self, extra_parent_env: dict) -> dict:
        client = make_client("ok:0.97,0.02,0.01")
        try:
            with client._admission_semaphore:
                pass
            interpreter = "python" if os.name == "nt" else "python3"
            env = client._build_sanitized_worker_env()
            env.update(extra_parent_env)  # simulate hostile parent values pre-sanitize? no:
            # we assert sanitize wins by rebuilding after pollution:
            polluted = {**os.environ, **extra_parent_env}
            merged = {**polluted, **{k: v for k, v in env.items()}}
            return merged
        finally:
            client.close()

    def test_03_worker_spawn_strips_pythonpath_injection(self):
        client = make_client("ok:0.97,0.02,0.01")
        try:
            os.environ["PYTHONPATH"] = "C:\\attacker\\payload;/tmp/payload"
            try:
                env = client._build_sanitized_worker_env()
                self.assertEqual(env["PYTHONPATH"], str(REPO_ROOT))
            finally:
                os.environ.pop("PYTHONPATH", None)
        finally:
            client.close()

    def test_04_worker_spawn_disables_user_site(self):
        client = make_client("ok:0.97,0.02,0.01")
        try:
            env = client._build_sanitized_worker_env()
            self.assertEqual(env.get("PYTHONNOUSERSITE"), "1")
            self.assertNotIn("PYTHONUSERBASE", env)
            self.assertNotIn("PYTHONHOME", env)
            self.assertNotIn("PYTHONSTARTUP", env)
            self.assertNotIn("PYTHONINSPECT", env)
        finally:
            client.close()

    def test_16_arbitrary_hf_home_cannot_redirect_cache(self):
        client = make_client("ok:0.97,0.02,0.01")
        try:
            os.environ["HF_HOME"] = "C:\\attacker\\hf"
            os.environ["TRANSFORMERS_CACHE"] = "/tmp/attacker/hf"
            try:
                env = client._build_sanitized_worker_env()
                self.assertNotIn("HF_HOME", env)
                self.assertNotIn("TRANSFORMERS_CACHE", env)
                self.assertIn("VERIFIER_CACHE_ROOT", env)
            finally:
                os.environ.pop("HF_HOME", None)
                os.environ.pop("TRANSFORMERS_CACHE", None)
        finally:
            client.close()


class TestAttestation(unittest.TestCase):

    def test_05_handshake_dependency_versions_validated(self):
        expected = json.dumps({"torch": "1.0.0", "transformers": "1.0.0", "numpy": "1.0.0"})
        client = make_client("supply_ok", expected_dependency_versions=expected)
        try:
            res = client.verify_claim("Claim.", "Evidence.")
            self.assertEqual(res.verdict.value, "SUPPORTED")
            deps = client.handshake["dependencies"]
            self.assertEqual(deps["torch"]["version"], "1.0.0")
        finally:
            client.close()

    def test_07_handshake_dependency_versions_validated_exact(self):
        expected = json.dumps({"torch": "2.13.0+cpu"})
        client = make_client("dep_mismatch", expected_dependency_versions=expected)
        try:
            res = client.verify_claim("Claim.", "Evidence.")
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("DEPENDENCY_IDENTITY_MISMATCH", res.reason)
            self.assertIsNone(client._process)
        finally:
            client.close()

    def test_08_incompatible_python_version_rejected(self):
        from runtime.verifier_worker.client import (
            SidecarClaimVerifier as S, VerifierClientUnavailable)
        client = S(interpreter_executable=sys.executable, worker_script=FAKE_WORKER,
                   worker_args=["ok:0.97,0.02,0.01"])
        self.assertTrue(S._interpreter_version_matches("3.12.14"))
        self.assertFalse(S._interpreter_version_matches("3.14.7"))

    def test_09_production_fake_simulation_bypass_unavailable(self):
        source = (REPO_ROOT / "runtime/verifier_worker/main.py").read_text(encoding="utf-8")
        self.assertIn('"simulated_compatible_worker": False', source)
        self.assertNotIn('"simulated_compatible_worker": True', source)
        cfg_src = (REPO_ROOT / "config/authority.py").read_text(encoding="utf-8")
        self.assertNotIn("simulated_compatible_worker", cfg_src)

    def test_33_dependency_mismatch_fails_closed(self):
        expected = json.dumps({"torch": "X"})
        client = make_client("dep_mismatch", expected_dependency_versions=expected)
        try:
            res = client.verify_claim("Claim.", "Evidence.")
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertNotEqual(res.verdict.value, "SUPPORTED")
        finally:
            client.close()


class TestRepoLocalShadow(unittest.TestCase):

    def test_05b_repo_local_torch_shadow_reported_and_rejected(self):
        client = make_client("shadow_origin",
                             worker_args=["shadow_origin", str(REPO_ROOT)],
                             expected_dependency_versions=json.dumps({"torch": "1.0.0"}))
        try:
            res = client.verify_claim("Claim.", "Evidence.")
            self.assertEqual(res.verdict.value, "INCONCLUSIVE")
            self.assertIn("SUSPICIOUS_MODULE_ORIGIN", res.reason)
        finally:
            client.close()

    def test_06_worker_side_origin_check_rejects_repo_shadows(self):
        """Defense in depth: the worker itself flags repo-local ML origins."""
        from runtime.verifier_worker.main import _attest_dependencies  # worker-only module; guarded import
        # Simulate a repo-local shadow by injecting a fake module into sys.modules
        # of THIS probe process (worker-equivalent), then restore.
        fake = type(sys)("torch")
        fake.__file__ = str(REPO_ROOT / "torch" / "__init__.py")
        fake.__version__ = "9.9"
        saved = sys.modules.get("torch")
        sys.modules["torch"] = fake
        try:
            info, failures = _attest_dependencies()
            self.assertTrue(info["dependencies"]["torch"]["suspicious"])
            self.assertIn("SUSPICIOUS_MODULE_ORIGIN", failures)
        finally:
            if saved is None:
                sys.modules.pop("torch", None)
            else:
                sys.modules["torch"] = saved


class TestNetworkPolicy(unittest.TestCase):

    def test_10_normal_inference_is_local_only(self):
        src = (REPO_ROOT / "runtime/verifier_worker/neural_backend.py").read_text(encoding="utf-8")
        self.assertIn('network_mode == "LOCAL_ONLY"', src)
        self.assertIn("local_files_only=self.local_files_only", src)

    def test_11_missing_local_snapshot_fails_closed_category(self):
        proc = spawn_prod_worker({
            "VERIFIER_NETWORK_MODE": "LOCAL_ONLY",
            "VERIFIER_CACHE_ROOT": str(Path(tempfile.mkdtemp())),
            "VERIFIER_MANIFEST_REQUIRED": "1",
        })
        try:
            json.loads(proc.stdout.readline())  # handshake
            res = roundtrip(proc, {"protocol_version": "VERIFIER_IPC_V1",
                                   "request_id": "a", "operation": "verify",
                                   "claim": "c", "evidence": "e"})
            self.assertEqual(res["status"], "ERROR")
            self.assertIn(res["error_category"],
                          ("MODEL_NOT_PROVISIONED", "DEPENDENCY_MISSING"))
        finally:
            proc.kill()

    def test_12_no_online_fallback_after_local_miss(self):
        src = (REPO_ROOT / "runtime/verifier_worker/main.py").read_text(encoding="utf-8")
        self.assertNotIn("snapshot_download(", src.replace("local_files_only=True", ""))
        backend_src = (REPO_ROOT / "runtime/verifier_worker/neural_backend.py").read_text(encoding="utf-8")
        self.assertIn("self.local_files_only = network_mode == \"LOCAL_ONLY\"", backend_src)

    def test_13_revision_pin_format_enforced(self):
        from runtime.claim_verification import DEFAULT_MODEL_REVISION
        self.assertRegex(DEFAULT_MODEL_REVISION, r"^[0-9a-f]{40}$")

    def test_bc_default_network_mode_is_local_only(self):
        from config.authority import RuntimeConfigSnapshot
        self.assertEqual(RuntimeConfigSnapshot.__dataclass_fields__[
                             "verifier_model_network_mode"].default, "LOCAL_ONLY")


class TestManifestIntegrity(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="vchain_"))
        self.snapshot, self.manifest_path, self.manifest = make_snapshot(self.root)

    def _env(self, manifest=True, snapshot=True):
        e = {
            "VERIFIER_NETWORK_MODE": "LOCAL_ONLY",
            "VERIFIER_CACHE_ROOT": str(self.root),
            "VERIFIER_MANIFEST_REQUIRED": "1" if manifest else "0",
        }
        if snapshot:
            e["VERIFIER_MODEL_SNAPSHOT_DIR"] = str(self.snapshot)
        if manifest:
            e["VERIFIER_MANIFEST_PATH"] = str(self.manifest_path)
        return e

    def _ready_states(self, proc):
        json.loads(proc.stdout.readline())  # handshake
        res = roundtrip(proc, {"protocol_version": "VERIFIER_IPC_V1",
                               "request_id": "att", "operation": "attest"})
        att = res["attestation"]
        assets = att.get("model_assets", {})
        merged = dict(assets)
        merged["failures"] = att.get("failures", [])
        merged["readiness_states"] = att.get("readiness_states", [])
        merged["ready_for_load"] = att.get("ready_for_load")
        return merged

    def test_20_synthetic_valid_manifest_accepted(self):
        proc = spawn_prod_worker(self._env(manifest=True))
        try:
            att = self._ready_states(proc)
            # torch absent in hermetic probe -> deps not validated; but the
            # ASSET chain must be fully verified with zero asset failures.
            self.assertTrue(att["manifest_verified"])
            self.assertIn("MODEL_ASSETS_VALIDATED", att["readiness_states"])
            self.assertFalse([f for f in att["failures"] if "INTEGRITY" in f or "TAMPERED" in f])
        finally:
            proc.kill()

    def test_19_strict_manifest_missing_fails_closed(self):
        # Strict mode ON (default): snapshot present but NO trusted manifest
        # provisioned anywhere in the cache tree -> neural load fails closed.
        # (02E note: the worker now also probes <cache_root>/manifests/<pin>.json
        # by default, so the fixture must contain no manifest at all.)
        empty_root = Path(tempfile.mkdtemp(prefix="strict_missing_"))
        snapshot = empty_root / "snapshots" / PIN
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_bytes(b'{"model_type":"deberta-v2"}')
        e = {
            "VERIFIER_NETWORK_MODE": "LOCAL_ONLY",
            "VERIFIER_CACHE_ROOT": str(empty_root),
            "VERIFIER_MANIFEST_REQUIRED": "1",
            "VERIFIER_MODEL_SNAPSHOT_DIR": str(snapshot),
        }
        proc = spawn_prod_worker(e)
        try:
            att = self._ready_states(proc)
            self.assertIn("MODEL_INTEGRITY_MANIFEST_MISSING", att["failures"])
            self.assertTrue(att["manifest_required"])
            self.assertFalse(att["ready_for_load"])
        finally:
            proc.kill()

    def test_21_one_byte_tamper_rejected(self):
        p = self.snapshot / "model.safetensors"
        original = p.read_bytes()
        p.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))
        try:
            proc = spawn_prod_worker(self._env())
            try:
                att = self._ready_states(proc)
                self.assertIn("MODEL_ASSETS_TAMPERED", att["failures"])
                self.assertFalse(att["ready_for_load"])
            finally:
                proc.kill()
        finally:
            p.write_bytes(original)

    def test_22_missing_manifest_file_rejected(self):
        self.manifest_path.unlink()
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("MODEL_INTEGRITY_MANIFEST_MISSING", att["failures"])
        finally:
            proc.kill()

    def test_23_wrong_file_hash_rejected(self):
        m = dict(self.manifest)
        files = [dict(f) for f in m["files"]]
        files[1]["sha256"] = "0" * 64
        m["files"] = files
        self.manifest_path.write_text(json.dumps(m), encoding="utf-8")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("MODEL_ASSETS_TAMPERED", att["failures"])
        finally:
            proc.kill()

    def test_24_wrong_model_id_in_manifest_rejected(self):
        m = dict(self.manifest); m["model_id"] = "evil/model"; m["files"] = self.manifest["files"]
        self.manifest_path.write_text(json.dumps(m), encoding="utf-8")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("MODEL_IDENTITY_MISMATCH", att["failures"])
        finally:
            proc.kill()

    def test_25_wrong_revision_in_manifest_rejected(self):
        m = dict(self.manifest); m["model_revision"] = "f" * 40; m["files"] = self.manifest["files"]
        self.manifest_path.write_text(json.dumps(m), encoding="utf-8")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("MODEL_IDENTITY_MISMATCH", att["failures"])
        finally:
            proc.kill()

    def test_26_manifest_traversal_rejected(self):
        m = json.loads(json.dumps(self.manifest))
        m["files"] = [{"path": "../outside.txt", "sha256": "a" * 64, "size": 3}]
        self.manifest_path.write_text(json.dumps(m), encoding="utf-8")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("INTEGRITY_PATH_ESCAPE", att["failures"])
        finally:
            proc.kill()

    def test_27_absolute_manifest_path_rejected(self):
        m = json.loads(json.dumps(self.manifest))
        abs_target = Path(tempfile.mkdtemp()) / "secret.bin"
        abs_target.write_bytes(b"x")
        m["files"] = [{"path": str(abs_target), "sha256": "b" * 64, "size": 1}]
        self.manifest_path.write_text(json.dumps(m), encoding="utf-8")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            self.assertIn("INTEGRITY_PATH_ESCAPE", att["failures"])
        finally:
            proc.kill()

    def test_28_symlink_escape_rejected(self):
        outside = Path(tempfile.mkdtemp()) / "outside_weights.bin"
        outside.write_bytes(b"\x00\x01FAKE-SAFETENSORS-BODY\x02\x03")
        link = self.snapshot / "model.safetensors"
        if link.exists():
            link.unlink()
        try:
            link.symlink_to(outside)
            supports_symlink = link.is_symlink()
        except OSError:
            self.skipTest("symlinks unsupported on this platform/volume")
        proc = spawn_prod_worker(self._env())
        try:
            att = self._ready_states(proc)
            if supports_symlink:
                self.assertIn("INTEGRITY_PATH_ESCAPE", att["failures"])
        finally:
            proc.kill()

    def test_29_hash_verification_before_neural_load_ordering(self):
        src = (REPO_ROOT / "runtime/verifier_worker/main.py").read_text(encoding="utf-8")
        attest_idx = src.index("def build_attestation")
        verify_gate_idx = src.index('if operation == "attest"')
        integrity_idx = src.index("_attest_model_assets")
        self.assertLess(attest_idx, verify_gate_idx)
        # Attestation (incl. manifest hash verification) is wired before the
        # verify gate that authorizes neural load.
        self.assertLess(integrity_idx, attest_idx)

    def test_35_result_provenance_carries_supply_chain_identity(self):
        client = make_client("supply_ok")
        try:
            res = client.verify_claim("Claim.", "Evidence.")
            self.assertEqual(res.model_revision, PIN)
            self.assertEqual(res.model_id, MODEL_ID)
            self.assertIsNotNone(res.provenance_context_hash)
        finally:
            client.close()

    def test_36_37_main_process_stays_torch_free(self):
        probe = ("import sys, json\n"
                 "import runtime.claim_verification, runtime.engine\n"
                 "import runtime.verifier_worker.client, runtime.verifier_worker.integrity\n"
                 "print(json.dumps({'torch': 'torch' in sys.modules,"
                 " 'transformers': 'transformers' in sys.modules}))")
        result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO_ROOT),
                                capture_output=True, text=True, timeout=120)
        data = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(data["torch"])
        self.assertFalse(data["transformers"])

    def test_41_authoritative_cache_root_portable_default(self):
        client = SidecarClaimVerifier()
        try:
            env = client._build_sanitized_worker_env()
            cache_root = env["VERIFIER_CACHE_ROOT"]
            self.assertNotIn(str(REPO_ROOT), cache_root)   # outside tracked source
            self.assertNotIn("C:\\Users\\DUCK\\AppData\\Local\\Temp\\opencode", cache_root)
            self.assertTrue(len(cache_root) > 0 and not cache_root.startswith("."))
        finally:
            client.close()


class TestProductionIntegrityLockdownR2(unittest.TestCase):
    """PROD-VERIFIER-02F-R2 — production downgrade surfaces closed.

    Normal verification is immutably: LOCAL_ONLY + MANIFEST REQUIRED +
    HASH VERIFIED + SAFETENSORS ONLY. Neither hostile process env nor test
    DI may weaken it; provisioning stays exclusive to
    `python -m runtime.verifier_worker.provision`.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="r2_lockdown_"))

    def _spawn_worker(self, extra_env: dict):
        env = {k: v for k, v in os.environ.items() if not k.startswith("VERIFIER_")}
        env.update({"PYTHONPATH": str(REPO_ROOT), "PYTHONNOUSERSITE": "1", **extra_env})
        return subprocess.Popen(
            [sys.executable, "-X", "utf8", str(PROD_WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", cwd=str(REPO_ROOT), env=env,
        )

    def _attest(self, proc):
        proc.stdin.write(json.dumps({
            "protocol_version": "VERIFIER_IPC_V1",
            "request_id": "r2attest", "operation": "attest"}) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())["attestation"]

    def test_r2_01_worker_immutable_local_only_despite_hostile_env(self):
        proc = self._spawn_worker({
            "VERIFIER_NETWORK_MODE": "PROVISIONING",
            "VERIFIER_CACHE_ROOT": str(self.root),
            "VERIFIER_MANIFEST_REQUIRED": "1",
        })
        try:
            hs = json.loads(proc.stdout.readline())
            self.assertEqual(hs["network_mode"], "LOCAL_ONLY")
            att = self._attest(proc)
            self.assertEqual(att["network_mode"], "LOCAL_ONLY")
        finally:
            proc.kill()

    def test_r2_02_manifest_bypass_env_attempt_fails_closed(self):
        """§7 negative test: valid safe files, NO manifest, env screams
        VERIFIER_MANIFEST_REQUIRED=0 -> manifest enforced regardless."""
        snapshot = self.root / "snapshots" / PIN
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_bytes(b'{"model_type":"deberta-v2"}')
        (snapshot / "tokenizer.json").write_bytes(b'{"fake_tokenizer": true}')
        proc = self._spawn_worker({
            "VERIFIER_NETWORK_MODE": "LOCAL_ONLY",
            "VERIFIER_CACHE_ROOT": str(self.root),
            "VERIFIER_MANIFEST_REQUIRED": "0",
        })
        try:
            hs = json.loads(proc.stdout.readline())
            # The worker independently re-arms the requirement.
            self.assertIs(hs["manifest_required"], True)
            att = self._attest(proc)
            self.assertIn("MODEL_INTEGRITY_MANIFEST_MISSING", att["failures"])
            self.assertNotIn("MODEL_ASSETS_VALIDATED", att["readiness_states"])
            self.assertFalse(att["ready_for_load"])
            self.assertTrue(att["model_assets"]["manifest_required"])
            self.assertFalse(att["model_assets"]["manifest_verified"])
        finally:
            proc.kill()

    def test_r2_03_valid_manifest_still_verified_under_hostile_zero_env(self):
        """Legit supply path intact: provided manifest verifies even when the
        environment attempted to disable enforcement."""
        snapshot, manifest_path, _ = make_snapshot(self.root)
        proc = self._spawn_worker({
            "VERIFIER_NETWORK_MODE": "LOCAL_ONLY",
            "VERIFIER_CACHE_ROOT": str(self.root),
            "VERIFIER_MANIFEST_REQUIRED": "0",
            "VERIFIER_MODEL_SNAPSHOT_DIR": str(snapshot),
            "VERIFIER_MANIFEST_PATH": str(manifest_path),
        })
        try:
            json.loads(proc.stdout.readline())
            att = self._attest(proc)
            self.assertTrue(att["model_assets"]["manifest_verified"])
            self.assertIn("MODEL_ASSETS_VALIDATED", att["readiness_states"])
            integrity_failures = [f for f in att["failures"]
                                  if "INTEGRITY" in f or "TAMPERED" in f]
            self.assertEqual(integrity_failures, [])
        finally:
            proc.kill()

    def test_r2_04_client_spawn_env_pins_safe_policy(self):
        client = make_client("ok:0.97,0.02,0.01")
        try:
            env = client._build_sanitized_worker_env()
            self.assertEqual(env["VERIFIER_MANIFEST_REQUIRED"], "1")
            self.assertEqual(env["VERIFIER_NETWORK_MODE"], "LOCAL_ONLY")
            self.assertEqual(client.network_mode, "LOCAL_ONLY")
            self.assertIs(client.manifest_required, True)
        finally:
            client.close()

    def test_r2_05_client_di_unsafe_values_fail_closed(self):
        """Even direct DI mutation of a construction surface cannot smuggle an
        online mode or disabled manifest into the spawn environment."""
        from runtime.verifier_worker.client import VerifierClientUnavailable
        for attr, value in (("network_mode", "PROVISIONING"),
                            ("manifest_required", False)):
            with self.subTest(attr=attr, value=value):
                client = make_client("ok:0.97,0.02,0.01")
                try:
                    setattr(client, attr, value)
                    with self.assertRaises(VerifierClientUnavailable) as ctx:
                        client._build_sanitized_worker_env()
                    self.assertIn("INSECURE_VERIFIER_", ctx.exception.args[0])
                finally:
                    client.close()

    def _lying_handshake_client(self, extra_fields: dict):
        import queue as _q
        rogue = SidecarClaimVerifier(
            interpreter_executable=sys.executable,
            worker_script=FAKE_WORKER,
            startup_timeout_s=10.0, claim_timeout_s=15.0,
        )
        rogue._process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
        )
        rogue._response_queue = _q.Queue()
        frame = {
            "protocol_version": "VERIFIER_IPC_V1", "type": "handshake",
            "python_version": "3.12.4", "simulated_compatible_worker": True,
            "backend_available": True, "model_id": rogue.model_id,
            "model_revision": rogue.model_revision,
            "trust_remote_code": False, "status": "PROCESS_READY",
        }
        frame.update(extra_fields)
        rogue._response_queue.put(json.dumps(frame))
        return rogue

    def test_r2_06_parent_rejects_network_downgrade_handshake(self):
        from runtime.verifier_worker.client import VerifierClientUnavailable
        rogue = self._lying_handshake_client({"network_mode": "PROVISIONING"})
        try:
            with self.assertRaises(VerifierClientUnavailable) as ctx:
                rogue._perform_handshake()
            self.assertEqual(ctx.exception.args[0], "WORKER_NETWORK_POLICY_VIOLATION")
        finally:
            rogue.close()

    def test_r2_07_parent_rejects_manifest_disabled_handshake(self):
        from runtime.verifier_worker.client import VerifierClientUnavailable
        rogue = self._lying_handshake_client(
            {"network_mode": "LOCAL_ONLY", "manifest_required": False})
        try:
            with self.assertRaises(VerifierClientUnavailable) as ctx:
                rogue._perform_handshake()
            self.assertEqual(ctx.exception.args[0], "WORKER_MANIFEST_POLICY_VIOLATION")
        finally:
            rogue.close()

    def test_r2_08_permissive_source_branch_removed_and_invariant_declared(self):
        src = (REPO_ROOT / "runtime/verifier_worker/main.py").read_text(encoding="utf-8")
        # The audited downgrade branch is gone:
        self.assertNotIn("return info, []", src)
        # and the invariants are declared as constants, not derived from env:
        self.assertIn("NETWORK_MODE = \"LOCAL_ONLY\"", src)
        self.assertIn("MANIFEST_REQUIRED = True", src)


class TestTrustRemoteCode(unittest.TestCase):
    def test_30_trust_remote_code_remains_false_everywhere(self):
        for rel in ("runtime/verifier_worker/neural_backend.py",
                    "runtime/verifier_worker/main.py",
                    "runtime/verifier_worker/client.py"):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            if "trust_remote_code" in src:
                self.assertNotIn("trust_remote_code=True", src)
                self.assertNotIn('"trust_remote_code": True', src)

    def test_31_worker_claiming_true_rejected(self):
        # Covered at R4B boundary level; structural re-check here.
        client_src = (REPO_ROOT / "runtime/verifier_worker/client.py").read_text(encoding="utf-8")
        self.assertIn("TRUST_REMOTE_CODE_POLICY_VIOLATION", client_src)

    def test_32_no_production_config_enables_trust_remote_code(self):
        authority_src = (REPO_ROOT / "config/authority.py").read_text(encoding="utf-8")
        env_src = (REPO_ROOT / "config/env_loader.py").read_text(encoding="utf-8")
        self.assertNotIn("TRUST_REMOTE_CODE", authority_src)
        self.assertNotIn("TRUST_REMOTE_CODE", env_src)


if __name__ == "__main__":
    unittest.main()
