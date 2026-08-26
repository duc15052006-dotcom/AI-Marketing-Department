"""Isolated verifier client (PROD-VERIFIER-02B/02C). Torch-free, main process.

Implements the production claim-verification boundary:

    Main runtime (Python 3.14)
      -> SidecarClaimVerifier / IsolatedClaimVerifier  [this module]
        -> parent-owned worker subprocess (target: Python 3.12)
          -> runtime.verifier_worker.neural_backend  [torch lives HERE only]

02C deadline authority:
    - ONE overall verification-gate deadline (monotonic) may be supplied per
      gate (engine Stage-6 scan). Every claim consumes REMAINING budget;
      no claim may reset the full timeout.
    - effective_claim_timeout = min(configured_per_claim, remaining_gate).
    - Waiting for verifier admission also consumes the same deadline.
    - There is NO authoritative run/stage deadline in RuntimeContext today
      (verified 02A/02C); the gate deadline is therefore verifier-local and
      capped against nothing external. Reported truthfully.

Fail-closed contract: EVERY failure mode below yields verdict INCONCLUSIVE
(never SUPPORTED, never fabricated provenance), with a truthful stable
category recorded in result.reason / last_error_category:
    INTERPRETER_NOT_CONFIGURED, WORKER_START_FAILURE, WORKER_STARTUP_TIMEOUT,
    TIMEOUT (request), BACKPRESSURE, WORKER_EXITED, BROKEN_PIPE,
    MALFORMED_RESPONSE, INVALID_RESPONSE_SCHEMA, PROTOCOL_ERROR (desync /
    oversized frame),     INPUT_TOO_LARGE, DEPENDENCY_MISSING, MODEL_LOAD_FAILED,
    INFERENCE_EXCEPTION, CLAIM_LIMIT_EXCEEDED,
    INSECURE_VERIFIER_NETWORK_MODE, INSECURE_VERIFIER_MANIFEST_DISABLED,
    WORKER_NETWORK_POLICY_VIOLATION, WORKER_MANIFEST_POLICY_VIOLATION.

Restart policy (deterministic): ONE bounded respawn after an unexpected
worker death; afterwards permanently unavailable until reset(). A timed-out
or protocol-corrupted request NEVER transparently retries the same claim;
the hung/corrupt worker is terminated (bounded wait -> kill).

Interpreter authority (no machine-specific hardcoded paths):
    explicit constructor argument
    > ConfigurationAuthority VERIFIER_PYTHON_EXECUTABLE
    > project-relative .verifier-venv interpreter if present
    > otherwise unavailable -> fail closed. NEVER in-process torch fallback.

Worker Python version contract: handshake major.minor must equal (3, 12),
EXCEPT hermetic test fakes which declare simulated_compatible_worker=true.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from runtime.claim_verification import (
    DEFAULT_MODEL_ID,
    DEFAULT_MODEL_REVISION,
    PROVISIONAL_TAU_CONTRADICTION,
    PROVISIONAL_TAU_ENTAILMENT,
    BaseClaimVerifier,
    ClaimVerificationResult,
    SemanticScores,
    VerificationVerdict,
    audit_deterministic_claim_guards,
    compute_evidence_content_hash,
    compute_provenance_context_hash,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKER_SCRIPT = REPO_ROOT / "runtime" / "verifier_worker" / "main.py"
PROJECT_VENV_INTERPRETERS = (
    REPO_ROOT / ".verifier-venv" / "Scripts" / "python.exe",  # Windows venv
    REPO_ROOT / ".verifier-venv" / "bin" / "python",           # POSIX venv
)

# Fallback bounds when ConfigurationAuthority is unavailable (e.g. unit tests).
FALLBACK_STARTUP_TIMEOUT_S = 20.0
FALLBACK_CLAIM_TIMEOUT_S = 30.0
FALLBACK_GATE_TIMEOUT_S = 120.0
FALLBACK_MAX_CLAIM_CHARS = 4000
FALLBACK_MAX_EVIDENCE_CHARS = 24000
FALLBACK_IPC_FRAME_LIMIT_BYTES = 1048576
FALLBACK_MAX_BATCH_SIZE = 32
GRACEFUL_SHUTDOWN_WAIT_S = 5.0
MAX_WORKER_RESPAWNS = 1
STDERR_TAIL_LINES = 40
STDERR_TAIL_MAX_BYTES = 8192
ADMISSION_MAX_WAITERS = 8

SUPPORTED_PYTHON_WORKER_VERSION = (3, 12)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _config_float(name: str, fallback: float) -> float:
    try:
        from config.authority import get_runtime_config
        return float(getattr(get_runtime_config(), name))
    except Exception:
        return fallback


def _config_int(name: str, fallback: int) -> int:
    try:
        from config.authority import get_runtime_config
        return int(getattr(get_runtime_config(), name))
    except Exception:
        return fallback


class VerifierClientUnavailable(Exception):
    """Raised internally when the isolated worker cannot be reached."""


class VerifierWorkerError(Exception):
    """Worker answered ERROR with a stable category."""

    def __init__(self, category: str, message: str = "") -> None:
        super().__init__(message or category)
        self.category = category


class VerifierResourceLimitError(Exception):
    """Explicit rejection of an over-limit batch/request. Never sliced."""


def _inconclusive(claim_text: str, source_id: Optional[str], ev_hash: Optional[str],
                  prov_hash: Optional[str], reason: str,
                  category: Optional[str] = None) -> ClaimVerificationResult:
    if category:
        reason = f"{category}: {reason}"
    return ClaimVerificationResult(
        claim_text=claim_text,
        source_id=source_id,
        evidence_content_hash=ev_hash,
        verdict=VerificationVerdict.INCONCLUSIVE,
        confidence=0.0,
        reason=reason,
        model_id=DEFAULT_MODEL_ID,
        model_revision=DEFAULT_MODEL_REVISION,
        backend="isolated_worker",
        provenance_context_hash=prov_hash,
    )


class SidecarClaimVerifier(BaseClaimVerifier):
    """Production verifier facade delegating NLI to the isolated worker."""

    def __init__(
        self,
        interpreter_executable: Optional[str] = None,
        worker_script: Optional[Path] = None,
        worker_args: Optional[List[str]] = None,
        tau_entailment: float = PROVISIONAL_TAU_ENTAILMENT,
        tau_contradiction: float = PROVISIONAL_TAU_CONTRADICTION,
        model_id: str = DEFAULT_MODEL_ID,
        model_revision: str = DEFAULT_MODEL_REVISION,
        startup_timeout_s: Optional[float] = None,
        claim_timeout_s: Optional[float] = None,
        max_claim_chars: Optional[int] = None,
        max_evidence_chars: Optional[int] = None,
        ipc_frame_limit_bytes: Optional[int] = None,
        max_batch_size: Optional[int] = None,
        expected_dependency_versions: Optional[str] = None,
        snapshot_dir_override: Optional[str] = None,
        manifest_path_override: Optional[str] = None,
    ) -> None:
        self.interpreter_executable = interpreter_executable
        self.worker_script = Path(worker_script) if worker_script else DEFAULT_WORKER_SCRIPT
        # Extra argv after the script path (e.g. hermetic fake-worker scenario).
        self.worker_args = list(worker_args) if worker_args else []
        self.tau_entailment = tau_entailment
        self.tau_contradiction = tau_contradiction
        self.model_id = model_id
        self.model_revision = model_revision

        self.startup_timeout_s = (
            startup_timeout_s if startup_timeout_s is not None
            else _config_float("verifier_worker_startup_timeout_s", FALLBACK_STARTUP_TIMEOUT_S))
        self.claim_timeout_s = (
            claim_timeout_s if claim_timeout_s is not None
            else _config_float("verifier_claim_timeout_s", FALLBACK_CLAIM_TIMEOUT_S))
        self.max_claim_chars = (
            max_claim_chars if max_claim_chars is not None
            else _config_int("verifier_max_claim_chars", FALLBACK_MAX_CLAIM_CHARS))
        self.max_evidence_chars = (
            max_evidence_chars if max_evidence_chars is not None
            else _config_int("verifier_max_evidence_chars", FALLBACK_MAX_EVIDENCE_CHARS))
        self.ipc_frame_limit_bytes = (
            ipc_frame_limit_bytes if ipc_frame_limit_bytes is not None
            else _config_int("verifier_ipc_frame_limit_bytes", FALLBACK_IPC_FRAME_LIMIT_BYTES))
        self.max_batch_size = (
            max_batch_size if max_batch_size is not None
            else _config_int("verifier_max_claims_per_gate", FALLBACK_MAX_BATCH_SIZE))

        self._lock = threading.RLock()
        # Bounded admission: one in-flight request; at most N registered
        # waiters beyond that. Waiters consume wall-clock from their own
        # caller-supplied deadline (backpressure is fail-closed).
        self._admission_semaphore = threading.Semaphore(1)
        self._admission_waiters = 0
        self._admission_lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._response_queue: "queue.Queue[Any]" = queue.Queue()
        self.handshake: Optional[Dict[str, Any]] = None
        self.unavailable_reason: Optional[str] = None
        self._respawns_used = 0
        self._failed_starts = 0
        self._spawned_pids: List[int] = []
        self.last_error_category: Optional[str] = None
        self._stderr_tail: deque = deque(maxlen=STDERR_TAIL_LINES)
        # None -> resolve from ConfigurationAuthority (production default:
        # certified baseline, enforced). "" -> explicitly disabled (test DI).
        self.expected_dependency_versions: Optional[str] = expected_dependency_versions
        self.cache_root: str = ""
        self.network_mode: str = ""
        self.manifest_required: Optional[bool] = None
        # Benchmark/DI surface: point the worker at a specific verified
        # snapshot/manifest (e.g. challenger candidates). Production leaves
        # these None so the worker resolves the provisioned production model.
        self.snapshot_dir_override: Optional[str] = snapshot_dir_override
        self.manifest_path_override: Optional[str] = manifest_path_override

        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Interpreter resolution (authoritative config; no hardcoded paths)
    # ------------------------------------------------------------------

    def _resolve_interpreter(self) -> str:
        if self.interpreter_executable:
            return str(self.interpreter_executable)
        try:
            from config.authority import get_runtime_config
            configured = get_runtime_config().verifier_python_executable
            if configured:
                return configured
        except Exception:
            pass
        for venv_path in PROJECT_VENV_INTERPRETERS:
            if venv_path.exists():
                return str(venv_path)
        raise VerifierClientUnavailable("INTERPRETER_NOT_CONFIGURED")

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    # Environment keys that must never leak into the worker launch: they can
    # redirect imports (shadowing) or the model cache to attacker/parent-
    # controlled locations.
    _STRIPPED_ENV_KEYS = (
        "PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE",
        "PYTHONSTARTUP", "PYTHONINSPECT",
        "HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE",
        "HUGGINGFACE_HUB_CACHE", "TORCH_HOME", "XDG_CACHE_HOME",
    )

    def _default_verifier_cache_root(self) -> str:
        # Portable, outside tracked source, not machine-hardcoded.
        return str(Path.home() / ".ai_marketing_department" / "verifier_model_cache")

    def _build_sanitized_worker_env(self) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if k not in self._STRIPPED_ENV_KEYS}
        # The ONLY PYTHONPATH the worker gets is the project root, so it can
        # import runtime.verifier_worker.* — arbitrary parent paths are stripped.
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["PYTHONNOUSERSITE"] = "1"  # user site-packages disabled

        try:
            from config.authority import get_runtime_config
            snap = get_runtime_config()
            network_mode = snap.verifier_model_network_mode
            cache_root = snap.verifier_cache_root or self._default_verifier_cache_root()
            manifest_required = snap.verifier_manifest_required
            expected_deps = snap.verifier_expected_dependency_versions
        except Exception:
            network_mode = "LOCAL_ONLY"
            cache_root = self._default_verifier_cache_root()
            manifest_required = True
            expected_deps = ""

        if self.expected_dependency_versions is None:
            self.expected_dependency_versions = expected_deps
        if not self.cache_root:
            self.cache_root = cache_root

        # Immutable production spawn policy (PROD-VERIFIER-02F-R2, defense in
        # depth on top of ConfigurationAuthority's fail-closed validation):
        # a normal production launch can NEVER request an online/provisioning
        # mode or a manifest-less worker. Unsafe values from ANY source are a
        # loud construction failure, never silently rewritten.
        resolved_network_mode = self.network_mode or network_mode or "LOCAL_ONLY"
        if resolved_network_mode != "LOCAL_ONLY":
            raise VerifierClientUnavailable("INSECURE_VERIFIER_NETWORK_MODE")
        if manifest_required is not True or (
                self.manifest_required is not None and self.manifest_required is not True):
            raise VerifierClientUnavailable("INSECURE_VERIFIER_MANIFEST_DISABLED")
        self.network_mode = "LOCAL_ONLY"
        self.manifest_required = True

        # Authoritative cache root MUST reach the isolated worker explicitly:
        # inherited HF/TORCH cache redirects are stripped below/above.
        env["VERIFIER_CACHE_ROOT"] = self.cache_root
        env["VERIFIER_NETWORK_MODE"] = "LOCAL_ONLY"
        env["VERIFIER_MANIFEST_REQUIRED"] = "1"
        # Parent-declared expected model identity (production defaults to the
        # certified pinned constants inside the worker; benchmark/DI parents
        # may attest a different explicitly-provisioned candidate).
        env["VERIFIER_EXPECTED_MODEL_ID"] = self.model_id
        env["VERIFIER_EXPECTED_MODEL_REVISION"] = self.model_revision
        if self.snapshot_dir_override:
            env["VERIFIER_MODEL_SNAPSHOT_DIR"] = self.snapshot_dir_override
            env["VERIFIER_MANIFEST_PATH"] = self.manifest_path_override or ""
        if self.expected_dependency_versions:
            env["VERIFIER_EXPECTED_DEPS"] = self.expected_dependency_versions
        return env

    def _spawn_worker(self) -> None:
        interpreter = self._resolve_interpreter()  # raises -> fail closed
        creationflags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        worker_env = self._build_sanitized_worker_env()
        try:
            self._process = subprocess.Popen(
                [interpreter, "-X", "utf8", str(self.worker_script), *self.worker_args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8",
                cwd=str(REPO_ROOT),
                creationflags=creationflags,
                env=worker_env,
            )
        except OSError as e:
            self.unavailable_reason = "WORKER_START_FAILURE"
            self.last_error_category = "WORKER_START_FAILURE"
            self._failed_starts += 1
            if self._failed_starts > MAX_WORKER_RESPAWNS:
                self._respawns_used = MAX_WORKER_RESPAWNS + 1
            raise VerifierClientUnavailable("WORKER_START_FAILURE") from e
        self._failed_starts = 0
        self._spawned_pids.append(self._process.pid)

        self._response_queue = queue.Queue()
        self._reader_thread = threading.Thread(
            target=self._read_stdout_loop, daemon=True, name="verifier-worker-stdout")
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr_loop, daemon=True, name="verifier-worker-stderr")
        self._stderr_thread.start()

    def _read_stdout_loop(self) -> None:
        """Bounded NDJSON frame reads. An oversized or unreadable line is a
        protocol/resource violation: poison the queue; the request path fails
        closed and invalidates the worker ("skip bad line and continue" is
        forbidden)."""
        assert self._process and self._process.stdout
        limit = self.ipc_frame_limit_bytes
        try:
            while True:
                line = self._process.stdout.readline(limit + 1)
                if not line:
                    break
                if len(line.encode("utf-8", "replace")) > limit or not line.endswith("\n"):
                    self._response_queue.put({"__violation__": "FRAME_TOO_LARGE"})
                    break
                self._response_queue.put(line)
        except Exception:
            pass
        finally:
            self._response_queue.put(None)  # EOF sentinel

    def _drain_stderr_loop(self) -> None:
        assert self._process and self._process.stderr
        try:
            for raw_line in self._process.stderr:
                sanitized = _CONTROL_CHAR_RE.sub("", raw_line.rstrip("\r\n"))[:512]
                if sanitized:
                    self._stderr_tail.append(sanitized)
        except Exception:
            pass

    @property
    def worker_stderr_tail(self) -> List[str]:
        """Bounded, sanitized diagnostic tail. Never returned to end users."""
        return list(self._stderr_tail)

    def _ensure_worker(self, deadline: Optional[float] = None) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None and self.handshake:
                return
            if self.unavailable_reason and self._respawns_used >= MAX_WORKER_RESPAWNS:
                raise VerifierClientUnavailable(self.unavailable_reason)
            if self._process is not None:
                self._respawns_used += 1
                if self._respawns_used > MAX_WORKER_RESPAWNS:
                    self.unavailable_reason = self.unavailable_reason or "WORKER_EXITED"
                    raise VerifierClientUnavailable("WORKER_RESPAWN_BUDGET_EXHAUSTED")
            self._close_process(graceful=False)
            self._spawn_worker()
            self._perform_handshake(deadline)

    def _perform_handshake(self, deadline: Optional[float] = None) -> None:
        started = time.monotonic()
        budget = self.startup_timeout_s
        hard_deadline = (deadline if deadline is not None
                         else time.monotonic() + budget)
        # Startup must respect BOTH its own configured budget and any caller
        # gate deadline already consumed before this call.
        configured_deadline = started + budget
        effective_deadline = min(hard_deadline, configured_deadline)
        while True:
            remaining = effective_deadline - time.monotonic()
            if remaining <= 0:
                category = ("GATE_DEADLINE_EXHAUSTED"
                            if (deadline is not None and time.monotonic() >= deadline)
                            else "WORKER_STARTUP_TIMEOUT")
                self.unavailable_reason = category
                self.last_error_category = category
                self._close_process(graceful=False)
                raise VerifierClientUnavailable(category)
            try:
                raw = self._response_queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if raw is None:
                # Worker died during startup: consumes respawn budget.
                self._respawns_used += 1
                self.unavailable_reason = "WORKER_EXITED_DURING_STARTUP"
                self.last_error_category = "WORKER_EXITED"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("WORKER_EXITED_DURING_STARTUP")
            if isinstance(raw, dict) and raw.get("__violation__"):
                self.last_error_category = "PROTOCOL_ERROR"
                self.unavailable_reason = "FRAME_TOO_LARGE"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("FRAME_TOO_LARGE")
            try:
                frame = json.loads(raw)
            except Exception:
                continue  # non-JSON stdout noise can never become a handshake
            from runtime.verifier_worker.protocol import validate_handshake, PROTOCOL_VERSION
            if not isinstance(frame, dict) or frame.get("type") != "handshake":
                continue
            if frame.get("protocol_version") != PROTOCOL_VERSION:
                self.unavailable_reason = "PROTOCOL_VERSION_MISMATCH"
                self.last_error_category = "PROTOCOL_VERSION_MISMATCH"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("PROTOCOL_VERSION_MISMATCH")
            if frame.get("model_id") != self.model_id or frame.get("model_revision") != self.model_revision:
                self.unavailable_reason = "MODEL_IDENTITY_MISMATCH"
                self.last_error_category = "MODEL_IDENTITY_MISMATCH"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("MODEL_IDENTITY_MISMATCH")
            if frame.get("trust_remote_code") is not False:
                self.unavailable_reason = "TRUST_REMOTE_CODE_POLICY_VIOLATION"
                self.last_error_category = "TRUST_REMOTE_CODE_POLICY_VIOLATION"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("TRUST_REMOTE_CODE_POLICY_VIOLATION")
            # Supply-chain policy attestation (PROD-VERIFIER-02F-R2): the
            # production worker must independently attest the immutable
            # LOCAL_ONLY + manifest-required invariants in its handshake.
            if frame.get("network_mode") != "LOCAL_ONLY":
                self.unavailable_reason = "WORKER_NETWORK_POLICY_VIOLATION"
                self.last_error_category = "WORKER_NETWORK_POLICY_VIOLATION"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("WORKER_NETWORK_POLICY_VIOLATION")
            if frame.get("manifest_required") is not True:
                self.unavailable_reason = "WORKER_MANIFEST_POLICY_VIOLATION"
                self.last_error_category = "WORKER_MANIFEST_POLICY_VIOLATION"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("WORKER_MANIFEST_POLICY_VIOLATION")
            if not frame.get("simulated_compatible_worker"):
                if not self._interpreter_version_matches(frame.get("python_version", "")):
                    self.unavailable_reason = "UNSUPPORTED_WORKER_PYTHON_VERSION"
                    self.last_error_category = "UNSUPPORTED_WORKER_PYTHON_VERSION"
                    self._close_process(graceful=False)
                    raise VerifierClientUnavailable("UNSUPPORTED_WORKER_PYTHON_VERSION")

            # Dependency identity attestation (PROD-VERIFIER-02D): when exact
            # expected versions are configured, any mismatch fails closed.
            expected = self._parse_expected_deps()
            if expected:
                reported = frame.get("dependencies") or {}
                for dep_name, dep_version in sorted(expected.items()):
                    actual = (reported.get(dep_name) or {}).get("version") \
                        if isinstance(reported.get(dep_name), dict) else None
                    if actual != dep_version:
                        self.unavailable_reason = "DEPENDENCY_IDENTITY_MISMATCH"
                        self.last_error_category = "DEPENDENCY_IDENTITY_MISMATCH"
                        self._close_process(graceful=False)
                        raise VerifierClientUnavailable(
                            f"DEPENDENCY_IDENTITY_MISMATCH: {dep_name} "
                            f"(expected {dep_version}, got {actual})")
                # Suspicious third-party origins: any ML module resolving from
                # inside the project source tree is a shadowing attack, UNLESS
                # it lives inside the worker's own isolated environment root
                # (the .verifier-venv reported by the worker itself). The
                # parent derives suspicion independently; a worker flag alone
                # is never trusted.
                repo_norm = os.path.normcase(os.path.normpath(str(REPO_ROOT))) + os.sep
                env_root = os.path.normcase(os.path.normpath(
                    (frame.get("dependencies") or {}).get("environment_root")
                    or (reported.get("environment_root") if isinstance(reported, dict) else "")
                    or "")) + os.sep if (frame.get("dependencies") or {}).get("environment_root") else None
                for dep_name, entry in sorted((reported or {}).items()):
                    if not isinstance(entry, dict):
                        continue
                    origin = entry.get("origin")
                    if origin and env_root:
                        o_norm = os.path.normcase(os.path.normpath(origin))
                        in_repo = o_norm.startswith(repo_norm)
                        in_env = o_norm.startswith(env_root)
                        suspicious = entry.get("suspicious") or (in_repo and not in_env)
                    elif origin:
                        suspicious = entry.get("suspicious") or (
                            os.path.normcase(os.path.normpath(origin)).startswith(repo_norm))
                    else:
                        suspicious = bool(entry.get("suspicious"))
                    if suspicious:
                        self.unavailable_reason = "SUSPICIOUS_MODULE_ORIGIN"
                        self.last_error_category = "SUSPICIOUS_MODULE_ORIGIN"
                        self._close_process(graceful=False)
                        raise VerifierClientUnavailable(
                            f"SUSPICIOUS_MODULE_ORIGIN: {dep_name}")
            self.handshake = frame
            return

    @staticmethod
    def _interpreter_version_matches(python_version: str) -> bool:
        try:
            parts = python_version.split(".")
            return (int(parts[0]), int(parts[1])) == SUPPORTED_PYTHON_WORKER_VERSION
        except Exception:
            return False

    def _parse_expected_deps(self) -> Dict[str, str]:
        if not self.expected_dependency_versions:
            return {}
        try:
            parsed = json.loads(self.expected_dependency_versions)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    # ------------------------------------------------------------------
    # Request/response: single-flight, correlation, bounded frames
    # ------------------------------------------------------------------

    def _invalidate_worker(self, category: str, reason_code: str) -> None:
        """Protocol corruption/desync: the stream can no longer be trusted."""
        self.last_error_category = category
        self.unavailable_reason = reason_code
        self._close_process(graceful=False)

    def _request(self, payload: Dict[str, Any],
                 deadline: Optional[float]) -> Dict[str, Any]:
        assert self._process and self._process.stdin and self.handshake
        from runtime.verifier_worker.protocol import PROTOCOL_VERSION

        request_id = uuid.uuid4().hex
        frame = {"protocol_version": PROTOCOL_VERSION,
                 "request_id": request_id, **payload}
        wire = json.dumps(frame, ensure_ascii=False).encode("utf-8")
        if len(wire) > self.ipc_frame_limit_bytes:
            self.last_error_category = "INPUT_TOO_LARGE"
            raise VerifierWorkerError("INPUT_TOO_LARGE", "IPC request frame exceeds limit")

        try:
            self._process.stdin.write(wire.decode("utf-8") + "\n")
            self._process.stdin.flush()
        except Exception as e:
            self.last_error_category = "BROKEN_PIPE"
            self.unavailable_reason = "BROKEN_PIPE"
            raise VerifierClientUnavailable("BROKEN_PIPE") from e

        from runtime.verifier_worker.protocol import validate_result_frame
        poll_budget = 0.25
        while True:
            remaining = (deadline - time.monotonic()) if deadline is not None else self.claim_timeout_s
            if deadline is not None and remaining <= 0:
                self.last_error_category = "TIMEOUT"
                self._close_process(graceful=False)  # kill hung worker
                raise VerifierClientUnavailable("TIMEOUT")
            if deadline is None and remaining <= 0:
                self.last_error_category = "TIMEOUT"
                self._close_process(graceful=False)
                raise VerifierClientUnavailable("TIMEOUT")
            try:
                raw = self._response_queue.get(timeout=min(max(remaining, 0.05), poll_budget))
            except queue.Empty:
                if self._process.poll() is not None:
                    self.unavailable_reason = "WORKER_EXITED"
                    self.last_error_category = "WORKER_EXITED"
                    raise VerifierClientUnavailable("WORKER_EXITED")
                continue
            if raw is None:
                # Worker died mid-request: consumes respawn budget.
                self._respawns_used += 1
                self.unavailable_reason = "WORKER_EXITED"
                self.last_error_category = "WORKER_EXITED"
                raise VerifierClientUnavailable("WORKER_EXITED")
            if isinstance(raw, dict) and raw.get("__violation__") == "FRAME_TOO_LARGE":
                self._invalidate_worker("PROTOCOL_ERROR", "FRAME_TOO_LARGE")
                raise VerifierClientUnavailable("FRAME_TOO_LARGE")
            try:
                response = json.loads(raw)
            except Exception:
                # Malformed frame: stream synchronization untrusted.
                self._invalidate_worker("PROTOCOL_ERROR", "MALFORMED_RESPONSE")
                raise VerifierClientUnavailable("MALFORMED_RESPONSE")
            if not isinstance(response, dict):
                self._invalidate_worker("PROTOCOL_ERROR", "INVALID_RESPONSE_SCHEMA")
                raise VerifierClientUnavailable("INVALID_RESPONSE_SCHEMA")
            if response.get("protocol_version") != PROTOCOL_VERSION:
                self._invalidate_worker("PROTOCOL_ERROR", "PROTOCOL_VERSION_MISMATCH")
                raise VerifierClientUnavailable("PROTOCOL_VERSION_MISMATCH")
            # Single-flight: ANY mismatched request_id is desynchronization,
            # not something to wait through. Fail immediately.
            if response.get("request_id") != request_id:
                self._invalidate_worker("PROTOCOL_ERROR", "REQUEST_ID_MISMATCH")
                raise VerifierClientUnavailable("REQUEST_ID_MISMATCH")
            if not validate_result_frame(response):
                self._invalidate_worker("PROTOCOL_ERROR", "INVALID_RESPONSE_SCHEMA")
                raise VerifierClientUnavailable("INVALID_RESPONSE_SCHEMA")
            if response.get("status") == "ERROR":
                category = response.get("error_category") or "INFERENCE_EXCEPTION"
                self.last_error_category = category
                raise VerifierWorkerError(category, str(response.get("message", "")))
            return response

    # ------------------------------------------------------------------
    # BaseClaimVerifier contract
    # ------------------------------------------------------------------

    def verify_claim(
        self,
        claim_text: str,
        evidence_text: str,
        claim_metadata: Optional[Dict[str, Any]] = None,
        source_metadata: Optional[Dict[str, Any]] = None,
        deadline_monotonic: Optional[float] = None,
    ) -> ClaimVerificationResult:
        claim_meta = claim_metadata or {}
        source_meta = source_metadata or {}
        source_id = source_meta.get("source_id") or source_meta.get("execution_id")
        ev_hash = compute_evidence_content_hash(evidence_text)
        prov_hash = compute_provenance_context_hash(claim_meta, source_meta)

        # Deterministic guard layer runs FIRST so scope/authority semantics
        # always take precedence over resource limits (PROD-VERIFIER-02C §27).
        guard_findings = audit_deterministic_claim_guards(
            claim_text=claim_text,
            evidence_text=evidence_text,
            claim_metadata=claim_meta,
            source_metadata=source_meta,
        )
        if not guard_findings.passed:
            g_name = str(guard_findings.guard_name)
            verdict = VerificationVerdict.INCONCLUSIVE
            if "SECURITY_SCOPE" in g_name or "PROVENANCE_SCOPE" in g_name:
                verdict = VerificationVerdict.SCOPE_VIOLATION
            elif "GEOGRAPHIC_SCOPE" in g_name or "MISMATCH" in g_name:
                verdict = VerificationVerdict.CONTRADICTED
            elif "MOCK" in g_name or "EXECUTION" in g_name:
                verdict = VerificationVerdict.UNSUPPORTED
            return ClaimVerificationResult(
                claim_text=claim_text,
                source_id=source_id,
                evidence_refs=[str(source_id)] if source_id else [],
                evidence_content_hash=ev_hash,
                verdict=verdict,
                confidence=1.0,
                reason=f"Blocked by deterministic guard: {guard_findings.reason}",
                model_id=self.model_id,
                model_revision=self.model_revision,
                backend="deterministic_guard",
                deterministic_findings=guard_findings,
                provenance_context_hash=prov_hash,
                epistemic_type_preserved=guard_findings.extracted_claim_values.get("claim_class"),
            )

        # Pre-IPC char/byte resource defense (DoS bound). Runs AFTER guards so
        # scope/authority semantics are never masked by resource categories.
        if len(claim_text) > self.max_claim_chars:
            self.last_error_category = "INPUT_TOO_LARGE"
            return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                 "claim exceeds configured character limit.", "INPUT_TOO_LARGE")
        if len(evidence_text) > self.max_evidence_chars:
            self.last_error_category = "INPUT_TOO_LARGE"
            return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                 "evidence exceeds configured character limit.", "INPUT_TOO_LARGE")

        # Pre-IPC request-frame bound: reject BEFORE spawning/sending so an
        # oversized frame can never reach the worker or the pipe.
        approx_frame_bytes = len(json.dumps({
            "protocol_version": "VERIFIER_IPC_V1",
            "request_id": "0" * 32,
            "operation": "verify",
            "claim": claim_text,
            "evidence": evidence_text,
        }, ensure_ascii=False).encode("utf-8"))
        if approx_frame_bytes > self.ipc_frame_limit_bytes:
            self.last_error_category = "INPUT_TOO_LARGE"
            return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                 "IPC request frame exceeds configured byte limit.",
                                 "INPUT_TOO_LARGE")

        # 2. Deadline composition: per-claim budget vs remaining gate budget.
        now = time.monotonic()
        per_claim_deadline = now + self.claim_timeout_s
        if deadline_monotonic is not None:
            effective_deadline = min(per_claim_deadline, deadline_monotonic)
        else:
            effective_deadline = per_claim_deadline
        if effective_deadline <= now:
            self.last_error_category = "GATE_DEADLINE_EXHAUSTED"
            return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                 "verification gate deadline exhausted before start.",
                                 "TIMEOUT")

        # 3. Bounded admission (backpressure). Waiting consumes the SAME
        #    effective deadline; no fresh timeout after acquisition.
        admitted = False
        with self._admission_lock:
            if self._admission_waiters >= ADMISSION_MAX_WAITERS:
                self.last_error_category = "BACKPRESSURE"
                return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                     "verifier admission queue full.", "BACKPRESSURE")
            self._admission_waiters += 1
        try:
            admitted = self._admission_semaphore.acquire(timeout=max(effective_deadline - time.monotonic(), 0.0))
            if not admitted:
                self.last_error_category = "BACKPRESSURE"
                return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                     "verifier busy; admission deadline expired.", "BACKPRESSURE")
        except KeyboardInterrupt:
            raise
        finally:
            if not admitted:
                with self._admission_lock:
                    self._admission_waiters -= 1
        try:
            # 4. Neural scoring via the ISOLATED WORKER ONLY.
            try:
                with self._lock:
                    self._ensure_worker(effective_deadline)
                    response = self._request({
                        "operation": "verify",
                        "claim": claim_text,
                        "evidence": evidence_text,
                    }, deadline=effective_deadline)
            except VerifierWorkerError as e:
                reason_map = {
                    "DEPENDENCY_MISSING": "NLI worker dependencies unavailable. Fails closed.",
                    "MODEL_LOAD_FAILED": "NLI worker model load failure. Fails closed.",
                    "MODEL_SAFE_WEIGHTS_UNAVAILABLE": "Safetensors weights unavailable/corrupt; "
                                                      "pickle fallback forbidden. Fails closed.",
                    "INFERENCE_EXCEPTION": "NLI worker inference exception. Fails closed.",
                    "BAD_REQUEST": "NLI worker rejected request. Fails closed.",
                    "INPUT_TOO_LARGE": "Tokenized pair exceeds supported inference context.",
                }
                category = e.category if e.category in ("INPUT_TOO_LARGE",) else e.category
                return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                     reason_map.get(e.category, f"NLI worker error ({e.category}). Fails closed."),
                                     category)
            except VerifierClientUnavailable as e:
                return _inconclusive(claim_text, source_id, ev_hash, prov_hash,
                                     f"NLI verifier unavailable ({e}). Fails closed.",
                                     self.last_error_category)
        finally:
            self._admission_semaphore.release()
            with self._admission_lock:
                self._admission_waiters -= 1

        # 5. Threshold authority remains in the MAIN process.
        p_ent = float(response["p_entailment"])
        p_neu = float(response["p_neutral"])
        p_con = float(response["p_contradiction"])

        if p_ent >= self.tau_entailment:
            verdict = VerificationVerdict.SUPPORTED
            confidence = p_ent
            reason = f"Verified with high entailment confidence (p_entailment={p_ent:.4f} >= {self.tau_entailment})."
        elif p_con >= self.tau_contradiction:
            verdict = VerificationVerdict.CONTRADICTED
            confidence = p_con
            reason = f"Contradiction detected (p_contradiction={p_con:.4f} >= {self.tau_contradiction})."
        else:
            verdict = VerificationVerdict.INCONCLUSIVE
            confidence = max(p_ent, p_con, p_neu)
            reason = (
                f"Evidence is inconclusive for this claim (p_entailment={p_ent:.4f} < {self.tau_entailment}, "
                f"p_contradiction={p_con:.4f} < {self.tau_contradiction})."
            )

        return ClaimVerificationResult(
            claim_text=claim_text,
            source_id=source_id,
            evidence_refs=[str(source_id)] if source_id else [],
            evidence_content_hash=ev_hash,
            verdict=verdict,
            confidence=round(confidence, 4),
            reason=reason,
            model_id=response.get("model_id", self.model_id),
            model_revision=response.get("model_revision", self.model_revision),
            backend=response.get("backend", "isolated_worker"),
            semantic_scores=SemanticScores(
                p_entailment=p_ent, p_neutral=p_neu, p_contradiction=p_con,
                argmax_label=response.get("argmax_label"),
                raw_latency_ms=float(response.get("latency_ms", 0.0)),
            ),
            provenance_context_hash=prov_hash,
        )

    def verify_batch(
        self,
        requests: Sequence[Tuple[str, str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]],
        deadline_monotonic: Optional[float] = None,
    ) -> List[ClaimVerificationResult]:
        """Deterministically bounded: over-limit batches are rejected WITHOUT
        slicing (silent slicing would leave tail claims unverified)."""
        if len(requests) > self.max_batch_size:
            self.last_error_category = "CLAIM_LIMIT_EXCEEDED"
            raise VerifierResourceLimitError(
                f"VERIFIER_RESOURCE_LIMIT: batch size {len(requests)} exceeds "
                f"configured maximum {self.max_batch_size}. Rejected without slicing.")
        return super().verify_batch(requests, deadline_monotonic=deadline_monotonic)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _close_process(self, graceful: bool) -> None:
        proc = self._process
        self._process = None
        self.handshake = None
        if proc is None:
            return
        try:
            if graceful and proc.stdin:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
            try:
                proc.wait(timeout=GRACEFUL_SHUTDOWN_WAIT_S if graceful else 0.5)
                return
            except Exception:
                pass
            try:
                proc.terminate()
                proc.wait(timeout=3.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        finally:
            pass

    def reset(self) -> None:
        """Explicit reinitialization (clears respawn budget/unavailability)."""
        with self._lock:
            self._close_process(graceful=True)
            self.unavailable_reason = None
            self._respawns_used = 0
            self._failed_starts = 0
            self.last_error_category = None

    def close(self) -> None:
        with self._lock:
            self._close_process(graceful=True)

    # Test/introspection surface -------------------------------------------------

    @property
    def worker_pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def spawned_pids(self) -> List[int]:
        return list(self._spawned_pids)

    uses_worker_boundary = True


# Production-facing alias preserving the historical public name without any
# torch import path in the main process.
IsolatedClaimVerifier = SidecarClaimVerifier
