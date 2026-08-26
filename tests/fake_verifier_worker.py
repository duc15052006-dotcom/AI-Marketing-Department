"""Deterministic FAKE verifier worker for hermetic boundary tests.

PROD-VERIFIER-02B test double ONLY. Contains no torch/transformers/network.
Selected exclusively via explicit dependency injection in tests:
    client = SidecarClaimVerifier(
        interpreter_executable=sys.executable,
        worker_script=REPO_ROOT / "tests" / "fake_verifier_worker.py",
        ...)

Scenarios (argv[1]):
    ok:<ent>,<neu>,<con>   healthy worker returning fixed scores
    dep_missing            handshake PROCESS_READY, verify -> DEPENDENCY_MISSING
    model_load_failure     verify -> MODEL_LOAD_FAILED
    inference_failure      verify -> INFERENCE_EXCEPTION
    malformed_json         emits a garbage line after handshake
    wrong_request_id       responds with request_id "WRONG"
    wrong_protocol_version responses use protocol_version "BOGUS"
    bad_schema             OK frame missing required score fields
    exit_immediate         exits before any output
    broken_pipe            handshake then closes stdout, keeps running
    stderr_noise           healthy, plus JSON-looking noise on stderr
    hang_before_handshake  sleeps forever before emitting anything
    deaf                   ignores stdin EOF; must be force-terminated

The fake declares simulated_compatible_worker=true so hermetic tests may run
under any host interpreter; the production worker never declares simulation.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

PROTOCOL_VERSION = "VERIFIER_IPC_V1"

MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
MODEL_REVISION = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"


def emit(frame: dict) -> None:
    sys.stdout.write(json.dumps(frame, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "ok:0.97,0.02,0.01"

    if scenario == "exit_immediate":
        return 0

    if scenario == "hang_before_handshake":
        time.sleep(600)
        return 0

    simulated = True  # test DI only
    handshake = {
        "protocol_version": PROTOCOL_VERSION,
        "type": "handshake",
        "python_version": platform.python_version(),
        "simulated_compatible_worker": simulated,
        "backend_available": True,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "trust_remote_code": False,
        # PROD-VERIFIER-02F-R2: hermetic fakes mirror the real worker's
        # immutable policy attestation so parent-side validation is exercised.
        "network_mode": "LOCAL_ONLY",
        "manifest_required": True,
        "status": "PROCESS_READY",
    }
    if scenario == "supply_ok":
        handshake["dependencies"] = {
            m: {"available": True, "version": f"1.0.0", "origin": "/opt/venv/lib/site-packages/" + m + "/__init__.py"}
            for m in ("torch", "transformers", "numpy")
        }
    if scenario == "shadow_origin":
        handshake["dependencies"] = {
            "torch": {"available": True, "version": "1.0.0",
                      "origin": str(Path(sys.argv[2]).resolve() / "torch" / "__init__.py")},
            "transformers": {"available": True, "version": "1.0.0",
                             "origin": "/opt/venv/lib/site-packages/transformers/__init__.py"},
            "numpy": {"available": True, "version": "1.0.0",
                      "origin": "/opt/venv/lib/site-packages/numpy/__init__.py"},
        }
    if scenario == "dep_mismatch":
        handshake["dependencies"] = {
            m: {"available": True, "version": "9.9.9", "origin": "/opt/venv/lib/site-packages/" + m + "/__init__.py"}
            for m in ("torch", "transformers", "numpy")
        }
    emit(handshake)

    if scenario == "broken_pipe":
        sys.stdout.flush()
        os.close(sys.stdout.fileno())
        time.sleep(600)
        return 0

    if scenario == "deaf":
        # Handshake emitted; then NEVER reads stdin (ignores EOF).
        # Parent graceful close must fall back to forced termination.
        time.sleep(600)
        return 0

    if scenario == "silent":
        # Handshake OK, then NEVER responds to requests (hung inference).
        time.sleep(600)
        return 0

    if scenario == "huge_frame":
        # Responds with a single line far beyond any sane frame limit.
        if len(sys.argv) > 2:
            pass
        big = "x" * 200000
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except Exception:
                continue
            emit({
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request.get("request_id"),
                "type": "result",
                "status": "OK",
                "p_entailment": 0.99, "p_neutral": 0.005, "p_contradiction": 0.005,
                "argmax_label": "ENTAILMENT",
                "backend": "fake", "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION, "latency_ms": 1.0,
                "noise": big,
            })
        return 0

    if scenario == "stderr_flood":
        for _ in range(400):
            sys.stderr.write("LOG-" + ("y" * 200) + "\n")
        sys.stderr.flush()

    if scenario == "malformed_json":
        sys.stdout.write("THIS IS NOT JSON {{{\n")
        sys.stdout.flush()

    if scenario in ("supply_ok", "shadow_origin", "dep_mismatch"):
        # Supply-chain scenarios: serve healthy scores after handshake so the
        # client's attestation decision is what is actually under test.
        pass

    if scenario == "stderr_noise":
        sys.stderr.write('{"type": "handshake", "fake": "noise from stderr"}\n')
        sys.stderr.write("worker log line: loading model...\n")

    scores_by_scenario = {
        "ok:0.97,0.02,0.01": (0.97, 0.02, 0.01),
        "ok:0.50,0.10,0.40": (0.50, 0.10, 0.40),
        "ok:0.05,0.10,0.85": (0.05, 0.10, 0.85),
        "ok:0.90,0.08,0.02": (0.90, 0.08, 0.02),
        "ok:0.8999,0.08,0.0201": (0.8999, 0.08, 0.0201),
        "ok:0.05,0.25,0.70": (0.05, 0.25, 0.70),
        "ok:0.05,0.2501,0.6999": (0.05, 0.2501, 0.6999),
    }

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            continue
        request_id = request.get("request_id")

        def respond(payload_extra: dict) -> None:
            frame = {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "type": "result",
                **payload_extra,
            }
            if scenario == "wrong_request_id":
                frame["request_id"] = "WRONG"
            if scenario == "wrong_protocol_version":
                frame["protocol_version"] = "BOGUS"
            emit(frame)

        if scenario.startswith("ok:") and scenario in scores_by_scenario:
            pe, pn, pc = scores_by_scenario[scenario]
            respond({
                "status": "OK",
                "p_entailment": pe,
                "p_neutral": pn,
                "p_contradiction": pc,
                "argmax_label": max(
                    {"ENTAILMENT": pe, "NEUTRAL": pn, "CONTRADICTION": pc}.items(),
                    key=lambda kv: kv[1])[0],
                "backend": "fake_pytorch_cpu",
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "latency_ms": 1.23,
            })
        elif scenario == "dep_missing":
            respond({"status": "ERROR", "error_category": "DEPENDENCY_MISSING",
                     "message": "simulated missing torch"})
        elif scenario == "model_load_failure":
            respond({"status": "ERROR", "error_category": "MODEL_LOAD_FAILED",
                     "message": "simulated weights unavailable"})
        elif scenario == "inference_failure":
            respond({"status": "ERROR", "error_category": "INFERENCE_EXCEPTION",
                     "message": "simulated CUDA OOM"})
        elif scenario == "bad_schema":
            # Missing required score fields entirely.
            respond({"status": "OK", "message": "incomplete frame"})
        elif scenario == "stderr_flood":
            respond({
                "status": "OK",
                "p_entailment": 0.97, "p_neutral": 0.02, "p_contradiction": 0.01,
                "argmax_label": "ENTAILMENT",
                "backend": "fake_pytorch_cpu",
                "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
                "latency_ms": 1.0,
            })
        elif scenario == "stderr_noise":
            respond({
                "status": "OK",
                "p_entailment": 0.97, "p_neutral": 0.02, "p_contradiction": 0.01,
                "argmax_label": "ENTAILMENT",
                "backend": "fake_pytorch_cpu",
                "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
                "latency_ms": 1.0,
            })
        elif scenario in ("supply_ok", "shadow_origin", "dep_mismatch"):
            respond({
                "status": "OK",
                "p_entailment": 0.97, "p_neutral": 0.02, "p_contradiction": 0.01,
                "argmax_label": "ENTAILMENT",
                "backend": "fake_pytorch_cpu",
                "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
                "latency_ms": 1.0,
            })
        else:
            respond({"status": "ERROR", "error_category": "BAD_REQUEST",
                     "message": f"unknown scenario {scenario}"})

    return 0


if __name__ == "__main__":
    sys.exit(main())
