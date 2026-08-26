"""Isolated NLI verifier worker entry point (PROD-VERIFIER-02B).

Executed ONLY under the configured verifier interpreter (target: Python 3.12).
Owns torch / transformers / model weights / device selection.

stdout discipline: PROTOCOL FRAMES ONLY (JSON-lines). All logging goes to
stderr. Any unexpected stdout write would corrupt the protocol; the parent
treats malformed stdout as fail-closed.

This module must never be imported by the main runtime process.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path

# Route ALL worker logging to stderr before any library can touch stdout.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("verifier_worker.main")

from runtime.claim_verification import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION  # noqa: E402
from runtime.verifier_worker.protocol import (  # noqa: E402
    ERR_BAD_REQUEST,
    ERR_INPUT_TOO_LARGE,
    ERR_INFERENCE_EXCEPTION,
    PROTOCOL_VERSION,
    WORKER_MAX_CLAIM_CHARS,
    WORKER_MAX_EVIDENCE_CHARS,
    WORKER_MAX_FRAME_BYTES,
)
from runtime.verifier_worker.neural_backend import NeuralBackend, VerifierBackendError  # noqa: E402


from typing import Optional, Tuple  # noqa: E402

# ---------------------------------------------------------------------------
# Supply-chain lockdown (PROD-VERIFIER-02F-R2). Normal production verification
# is IMMUTABLY LOCAL_ONLY + manifest REQUIRED + hash verified + safetensors
# only. Unsafe values inherited from the parent environment are never honored:
# they are reported to stderr and the safe invariant is enforced regardless.
# Provisioning / model download NEVER enters this module; it exists solely as
# the explicit command `python -m runtime.verifier_worker.provision`.
# ---------------------------------------------------------------------------
_inherited_network_mode = os.environ.get("VERIFIER_NETWORK_MODE", "").strip().upper()
NETWORK_MODE = "LOCAL_ONLY"
if _inherited_network_mode not in ("", "LOCAL_ONLY"):
    logger.error(
        "Refusing inherited VERIFIER_NETWORK_MODE='%s': normal workers are "
        "immutably LOCAL_ONLY.", _inherited_network_mode)
# Expected model identity: production defaults to the certified pinned
# constants; a benchmark/DI parent may override BOTH fields together to
# attest a different explicitly-provisioned candidate.
EXPECTED_MODEL_ID = os.environ.get("VERIFIER_EXPECTED_MODEL_ID", "") or None
EXPECTED_MODEL_REVISION = os.environ.get("VERIFIER_EXPECTED_MODEL_REVISION", "") or None
CACHE_ROOT = os.environ.get("VERIFIER_CACHE_ROOT", "")
_inherited_manifest_flag = os.environ.get("VERIFIER_MANIFEST_REQUIRED", "").strip().lower()
MANIFEST_REQUIRED = True
if _inherited_manifest_flag in ("0", "false", "no", "off"):
    logger.error(
        "Refusing inherited VERIFIER_MANIFEST_REQUIRED='%s': production "
        "workers ALWAYS require an integrity manifest.",
        _inherited_manifest_flag)
elif _inherited_manifest_flag not in ("", "1", "true", "yes", "on"):
    logger.error(
        "Ignoring unrecognized VERIFIER_MANIFEST_REQUIRED='%s'; manifest "
        "requirement stays enforced.", _inherited_manifest_flag)


def _default_snapshot_dir() -> str:
    """Provisioned layout: <cache_root>/snapshots/<pinned commit>. Resolved by
    the explicit provisioning command; normal workers read it LOCAL_ONLY."""
    if CACHE_ROOT and len(os.environ.get("VERIFIER_MODEL_SNAPSHOT_DIR", "")) == 0:
        candidate = Path(CACHE_ROOT) / "snapshots" / DEFAULT_MODEL_REVISION
        return str(candidate)
    return ""


def _default_manifest_path() -> str:
    if CACHE_ROOT:
        candidate = Path(CACHE_ROOT) / "manifests" / f"{DEFAULT_MODEL_REVISION}.json"
        return str(candidate)
    return ""


SNAPSHOT_DIR = os.environ.get("VERIFIER_MODEL_SNAPSHOT_DIR", "") or _default_snapshot_dir()
MANIFEST_PATH = os.environ.get("VERIFIER_MANIFEST_PATH", "") or _default_manifest_path()

THIRD_PARTY_MODULES = (
    "torch", "transformers", "numpy",
    "huggingface_hub", "tokenizers", "safetensors",
)


def _module_origin(name: str) -> Optional[str]:
    try:
        mod = __import__(name)
        return getattr(mod, "__file__", None)
    except Exception:
        return None


def _attest_dependencies() -> Tuple[Dict[str, Any], List[str]]:
    """Return (dependency attestation dict, failure categories).

    Shadow rule: a third-party ML module resolving from the PROJECT SOURCE
    tree is an attack. Resolving from THIS worker environment's own
    site-packages (.verifier-venv, reported as environment_root) is the
    legitimate isolated installation.
    """
    deps: Dict[str, Any] = {}
    failures: List[str] = []
    repo_root = str(Path(__file__).resolve().parents[2])
    env_root = os.path.normcase(os.path.normpath(sys.prefix))
    for name in THIRD_PARTY_MODULES:
        origin = _module_origin(name)
        version = None
        if origin is not None:
            try:
                mod = __import__(name)
                version = getattr(mod, "__version__", None)
            except Exception:
                pass
        entry: Dict[str, Any] = {"available": origin is not None,
                                 "version": version, "origin": origin}
        # Repo-local shadow rejection: third-party ML code must never resolve
        # from the project source tree UNLESS it lives inside this worker's
        # own isolated environment root.
        if origin is not None:
            norm = os.path.normcase(os.path.normpath(origin))
            in_repo = norm.startswith(os.path.normcase(repo_root) + os.sep)
            in_env = norm.startswith(env_root + os.sep)
            if in_repo and not in_env:
                entry["suspicious"] = True
                failures.append("SUSPICIOUS_MODULE_ORIGIN")
        deps[name] = entry
    core_ok = all(deps[m]["available"] for m in ("torch", "transformers"))
    if not core_ok:
        failures.append("DEPENDENCY_MISSING")
    else:
        # torch/transformers present => numpy required by inference path.
        if not deps["numpy"]["available"]:
            failures.append("DEPENDENCY_MISSING")
    return {"dependencies": deps, "environment_root": sys.prefix}, failures


def _attest_model_assets() -> Tuple[Dict[str, Any], List[str]]:
    """Resolve + verify local snapshot/manifest BEFORE any model load."""
    from runtime.verifier_worker.integrity import (
        IntegrityFailure, load_manifest, verify_snapshot_against_manifest,
    )
    info: Dict[str, Any] = {
        "network_mode": NETWORK_MODE,
        "cache_root_configured": bool(CACHE_ROOT),
        "manifest_required": MANIFEST_REQUIRED,
        "snapshot_resolved": False,
        "manifest_verified": False,
        "verified_files": [],
    }
    failures: List[str] = []

    if not CACHE_ROOT:
        failures.append("MODEL_CACHE_ROOT_UNCONFIGURED")
        return info, failures

    snapshot_dir = SNAPSHOT_DIR
    manifest_path = MANIFEST_PATH
    if snapshot_dir and not manifest_path:
        candidate = Path(snapshot_dir).parent / "manifest.json"
        if candidate.is_file():
            manifest_path = str(candidate)

    if not snapshot_dir or not Path(snapshot_dir).is_dir():
        # LOCAL_ONLY + absent verified assets = not provisioned. No download.
        failures.append("MODEL_NOT_PROVISIONED" if NETWORK_MODE == "LOCAL_ONLY"
                        else "MODEL_SNAPSHOT_UNRESOLVED")
        return info, failures
    info["snapshot_resolved"] = True
    info["snapshot_dir_name"] = Path(snapshot_dir).name  # name only, no full path

    if not manifest_path:
        # Manifest absence is NEVER survivable (PROD-VERIFIER-02F-R2): no
        # MODEL_ASSETS_VALIDATED state is reachable without a trusted,
        # hash-verified manifest.
        failures.append("MODEL_INTEGRITY_MANIFEST_MISSING")
        return info, failures

    try:
        manifest = load_manifest(Path(manifest_path))
        verified = verify_snapshot_against_manifest(
            manifest=manifest,
            snapshot_dir=Path(snapshot_dir),
            cache_root=Path(CACHE_ROOT),
            expected_model_id=EXPECTED_MODEL_ID or DEFAULT_MODEL_ID,
            expected_model_revision=EXPECTED_MODEL_REVISION or DEFAULT_MODEL_REVISION,
        )
        info["manifest_verified"] = True
        info["verified_files"] = verified
        info["manifest_model_revision"] = manifest.get("model_revision")
    except IntegrityFailure as e:
        failures.append(e.category)
        info["integrity_error"] = e.category
    return info, failures


def build_attestation(backend: "NeuralBackend") -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    states = ["PROCESS_READY"]
    dep_info, dep_failures = _attest_dependencies()
    payload.update(dep_info)
    if not dep_failures:
        states.append("DEPENDENCIES_VALIDATED")
    asset_info, asset_failures = _attest_model_assets()
    payload["model_assets"] = {k: v for k, v in asset_info.items()}
    # Belt-and-braces (PROD-VERIFIER-02F-R2): MODEL_ASSETS_VALIDATED is only
    # reachable when the manifest was actually present AND hash-verified —
    # never merely because the failure list happens to be empty.
    if not asset_failures and asset_info.get("manifest_verified"):
        states.append("MODEL_ASSETS_VALIDATED")
    payload["readiness_states"] = states
    payload["ready_for_load"] = ("DEPENDENCIES_VALIDATED" in states
                                 and "MODEL_ASSETS_VALIDATED" in states)
    payload["failures"] = dep_failures + [f for f in asset_failures]
    payload["backend_available"] = backend.dependencies_available()
    payload["network_mode"] = NETWORK_MODE
    return payload


def emit(frame: dict) -> None:
    """Write a single protocol frame to stdout. Protocol frames only."""
    sys.stdout.write(json.dumps(frame, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# NOTE (logging contract): worker logs must never contain claim text,
# evidence text, or unnecessary scope identifiers. Operational metadata only.


def read_bounded_line(stream, limit_bytes: int) -> Tuple[Optional[str], bool]:
    """Bounded NDJSON read: never allocates beyond limit+1 bytes worth of
    characters. Returns (line, oversized). oversized=True means the frame
    exceeded the limit and the stream must be treated as untrusted."""
    chars: list = []
    total_bytes = 0
    while True:
        ch = stream.read(1)
        if ch == "":
            return "".join(chars) or None, False  # EOF
        if ch == "\n":
            return "".join(chars), False
        chars.append(ch)
        total_bytes += len(ch.encode("utf-8"))
        if total_bytes > limit_bytes:
            return None, True


def main() -> int:
    expected_id = EXPECTED_MODEL_ID or DEFAULT_MODEL_ID
    expected_rev = EXPECTED_MODEL_REVISION or DEFAULT_MODEL_REVISION
    backend = NeuralBackend(
        model_id=expected_id,
        model_revision=expected_rev,
        network_mode=NETWORK_MODE,
        local_snapshot_dir=SNAPSHOT_DIR,
    )
    attestation: Optional[dict] = None

    handshake = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "handshake",
        "python_version": platform.python_version(),
        "simulated_compatible_worker": False,
        "backend_available": backend.dependencies_available(),
        "model_id": expected_id,
        "model_revision": expected_rev,
        "trust_remote_code": False,
        "network_mode": NETWORK_MODE,
        "manifest_required": MANIFEST_REQUIRED,
        "environment_root": sys.prefix,
        "status": "PROCESS_READY",
    }
    emit(handshake)

    while True:
        line, oversized = read_bounded_line(sys.stdin, WORKER_MAX_FRAME_BYTES)
        if oversized:
            # Frame exceeded the hard limit: the stream can no longer be
            # trusted for resynchronization -> fail closed (non-zero exit).
            logger.error("Request frame exceeded size limit; failing closed.")
            return 2
        if line is None:
            break  # clean EOF: parent closed stdin
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("frame is not an object")
        except Exception:
            logger.warning("Unparseable request frame received.")
            continue  # cannot correlate a request_id; skip silently (parent times out / fails closed)

        protocol_ok = request.get("protocol_version") == PROTOCOL_VERSION
        request_id = request.get("request_id")
        operation = request.get("operation")

        if operation == "attest":
            if attestation is None:
                attestation = build_attestation(backend)
            if isinstance(request_id, str):
                emit({
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "type": "result",
                    "status": "OK",
                    "attestation": attestation,
                })
            continue

        if not protocol_ok or not isinstance(request_id, str) or operation != "verify":
            logger.warning("Rejected request frame (protocol/operation mismatch).")
            if isinstance(request_id, str):
                emit({
                    "protocol_version": PROTOCOL_VERSION,
                    "request_id": request_id,
                    "type": "result",
                    "status": "ERROR",
                    "error_category": ERR_BAD_REQUEST,
                    "message": "protocol version or operation rejected",
                })
            continue

        claim = request.get("claim")
        evidence = request.get("evidence")

        # Independent worker-side resource validation (defense in depth):
        # do not trust parent-side limits. Runs BEFORE the readiness gate so
        # untrusted oversized input is always rejected at this boundary.
        if not isinstance(claim, str) or not isinstance(evidence, str) \
                or len(claim) > WORKER_MAX_CLAIM_CHARS or len(evidence) > WORKER_MAX_EVIDENCE_CHARS:
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                "status": "ERROR",
                "error_category": ERR_INPUT_TOO_LARGE,
                "message": "claim/evidence missing or exceeds worker-side character limits",
            })
            continue

        # verify requires a completed, passing attestation (fail closed).
        if attestation is None:
            attestation = build_attestation(backend)
        if not attestation.get("ready_for_load"):
            first_failure = next(iter(attestation.get("failures", [])), "MODEL_NOT_PROVISIONED")
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                "status": "ERROR",
                "error_category": first_failure if first_failure != "DEPENDENCY_MISSING" else "DEPENDENCY_MISSING",
                "message": f"readiness gate failed: {', '.join(attestation.get('failures', []))}",
                "model_id": expected_id,
                "model_revision": expected_rev,
            })
            continue

        try:
            scores = backend.score(evidence_text=evidence, claim_text=claim)
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                "status": "OK",
                **scores,
                "model_id": expected_id,
                "model_revision": expected_rev,
            })
        except VerifierBackendError as e:
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                "status": "ERROR",
                "error_category": e.category if e.category else ERR_INFERENCE_EXCEPTION,
                "message": str(e),
            })
        except Exception as e:  # absolute fail-closed containment
            logger.error("Unhandled worker exception: %s", e, exc_info=True)
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                "status": "ERROR",
                "error_category": ERR_INFERENCE_EXCEPTION,
                "message": type(e).__name__,
            })

    return 0


if __name__ == "__main__":
    sys.exit(main())
