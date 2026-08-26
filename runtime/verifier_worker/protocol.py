"""Verifier IPC Protocol (PROD-VERIFIER-02B). Torch-free shared contract.

Transport: parent-owned subprocess, newline-delimited JSON on stdin/stdout.
stdout carries PROTOCOL FRAMES ONLY; all worker logging goes to stderr.

Handshake frame (worker -> parent, first line):
{
  "protocol_version": "VERIFIER_IPC_V1",
  "type": "handshake",
  "python_version": "3.12.4",
  "simulated_compatible_worker": false,     # true ONLY from hermetic test fakes
  "backend_available": false | true,        # torch+transformers importable?
  "model_id": "...",
  "model_revision": "...",
   "trust_remote_code": false,
  "network_mode": "LOCAL_ONLY",           # immutable normal-worker policy
  "manifest_required": true,              # immutable normal-worker policy
   "status": "PROCESS_READY"
}
Readiness truth rules:
  - PROCESS_READY means the process is alive and speaking the protocol.
  - backend_available=false means dependencies are missing: every verify
    request will be answered with ERROR/DEPENDENCY_MISSING.
  - The parent must never treat handshake as MODEL_LOADED; model load is lazy
    inside the worker and reported per-response.

Request frame (parent -> worker):
{"protocol_version": ..., "request_id": "<uuid>", "operation": "verify",
 "claim": "...", "evidence": "..."}

Response frame (worker -> parent):
{"protocol_version": ..., "request_id": ..., "type": "result", "status":
 "OK" | "ERROR", "p_entailment"?, "p_neutral"?, "p_contradiction"?,
 "argmax_label"?, "backend"?, "model_id"?, "model_revision"?,
 "latency_ms"?, "error_category"?, "message"?}

No pickle. No arbitrary Python objects. Unknown extra keys are ignored;
missing REQUIRED keys invalidate the frame (fail closed).
"""

PROTOCOL_VERSION = "VERIFIER_IPC_V1"

OPERATION_VERIFY = "verify"

HANDSHAKE_REQUIRED_KEYS = ("protocol_version", "type", "python_version", "status")
RESULT_REQUIRED_OK_KEYS = ("protocol_version", "request_id", "type", "status",
                           "p_entailment", "p_neutral", "p_contradiction")
RESULT_REQUIRED_ERROR_KEYS = ("protocol_version", "request_id", "type", "status",
                              "error_category")

# Error categories (stable contract strings)
ERR_BAD_REQUEST = "BAD_REQUEST"
ERR_DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
ERR_MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
ERR_INFERENCE_EXCEPTION = "INFERENCE_EXCEPTION"
ERR_INPUT_TOO_LARGE = "INPUT_TOO_LARGE"

# Bounded NDJSON defense-in-depth (worker side; mirrors client config).
# The worker independently rejects oversized frames/inputs even if the
# parent is bypassed or buggy. Parent must not be fully trusted.
WORKER_MAX_CLAIM_CHARS = 4000
WORKER_MAX_EVIDENCE_CHARS = 24000
WORKER_MAX_FRAME_BYTES = 1048576


def validate_handshake(frame) -> bool:
    return (
        isinstance(frame, dict)
        and all(k in frame for k in HANDSHAKE_REQUIRED_KEYS)
        and frame.get("protocol_version") == PROTOCOL_VERSION
        and frame.get("type") == "handshake"
    )


def validate_result_frame(frame) -> bool:
    if not isinstance(frame, dict):
        return False
    if frame.get("protocol_version") != PROTOCOL_VERSION:
        return False
    if frame.get("type") != "result":
        return False
    status = frame.get("status")
    if status == "OK":
        return all(k in frame for k in RESULT_REQUIRED_OK_KEYS)
    if status == "ERROR":
        return all(k in frame for k in RESULT_REQUIRED_ERROR_KEYS)
    return False
