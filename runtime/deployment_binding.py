"""Deterministic Final-CMO deployment provenance binding.

This module does not grant execution authority. It binds a deployment-ready
Final CMO output to the durable RuntimeContext checkpoint that committed that
output's semantic hash. ToolGateway/PolicyEngine remain the execution and
human-approval authorities.
"""

from __future__ import annotations

import copy
import hashlib
import json
import weakref
from threading import RLock
from typing import Any, Dict, Optional

from schemas.model_hooks import register_model_post_init_hook


DEPLOYMENT_BINDING_STATE_KEY = "final_cmo_deployment_binding"
DEPLOYMENT_PROVENANCE_FIELD = "deployment_provenance"
DEPLOYMENT_ERROR_PREFIX = "FINAL_CMO_DEPLOYMENT_PROVENANCE_REQUIRED"
LEGACY_RUNTIME_PUBLISH_PLACEHOLDER = "Campaign Go-To-Market Plan"

_BOUND_CONTEXTS: Dict[str, weakref.ReferenceType[Any]] = {}
_APPROVAL_REFERENCE_BY_EXECUTION: Dict[str, str] = {}
_REGISTRY_LOCK = RLock()


def _fail(detail: str) -> None:
    raise RuntimeError(f"{DEPLOYMENT_ERROR_PREFIX}: {detail}")


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def final_cmo_semantic_output_hash(output: Dict[str, Any]) -> str:
    """Hash Final CMO semantic output while excluding derived provenance metadata."""
    if not isinstance(output, dict):
        _fail("Final CMO output must be a mapping.")
    semantic_output = copy.deepcopy(output)
    semantic_output.pop(DEPLOYMENT_PROVENANCE_FIELD, None)
    canonical = json.dumps(
        semantic_output,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding_id(run_id: str, output_hash: str) -> str:
    raw = f"FINAL_CMO_DEPLOYMENT:{run_id}:{output_hash}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return f"FCMO-BIND-{digest[:24]}"


def _expected_seed(context: Any, output: Dict[str, Any]) -> Dict[str, Any]:
    output_hash = final_cmo_semantic_output_hash(output)
    return {
        "run_id": str(context.run_id),
        "business_id": getattr(context, "business_id", None),
        "project_id": getattr(context, "project_id", None),
        "chat_id": getattr(context, "chat_id", None),
        "binding_id": _binding_id(str(context.run_id), output_hash),
        "status": "READY_FOR_DEPLOYMENT",
        "output_hash": output_hash,
    }


def prepare_final_cmo_checkpoint_binding(context: Any) -> bool:
    """Place an immutable deployment seed in working_state before checkpoint hashing."""
    if _enum_value(getattr(context, "current_stage", None)) != "FINAL_CMO":
        return False
    if _enum_value(getattr(context, "status", None)) != "RUNNING":
        return False

    output = getattr(context, "stage_outputs", {}).get("final_cmo")
    if not isinstance(output, dict) or output.get("status") != "READY_FOR_DEPLOYMENT":
        return False
    content = output.get("master_gtm_plan_markdown")
    if not isinstance(content, str) or not content.strip():
        _fail("Deployment-ready Final CMO output has no publishable Markdown content.")

    # Already committed. Later WAITING/RUNNING approval checkpoints must not
    # silently rebind the deployment artifact.
    if isinstance(output.get(DEPLOYMENT_PROVENANCE_FIELD), dict):
        return False

    getattr(context, "working_state")[DEPLOYMENT_BINDING_STATE_KEY] = _expected_seed(context, output)
    return True


def register_final_cmo_checkpoint(context: Any, checkpoint: Any, prepared: bool) -> None:
    """Attach derived checkpoint provenance and register the live bound context."""
    if not prepared:
        return

    output = getattr(context, "stage_outputs", {}).get("final_cmo")
    if not isinstance(output, dict) or output.get("status") != "READY_FOR_DEPLOYMENT":
        _fail("Final CMO changed before deployment checkpoint registration.")

    expected_seed = _expected_seed(context, output)
    snapshot = getattr(checkpoint, "working_state_snapshot", {}) or {}
    if snapshot.get(DEPLOYMENT_BINDING_STATE_KEY) != expected_seed:
        _fail("Final CMO deployment seed was not committed by the checkpoint.")
    if _enum_value(getattr(checkpoint, "stage", None)) != "FINAL_CMO":
        _fail("Deployment checkpoint is not a FINAL_CMO checkpoint.")
    if _enum_value(getattr(checkpoint, "status", None)) != "RUNNING":
        _fail("Deployment checkpoint was not created from an active successful run.")
    if getattr(checkpoint, "calculate_checkpoint_hash")() != getattr(checkpoint, "checkpoint_hash", ""):
        _fail("Durable Final CMO checkpoint integrity verification failed.")

    output[DEPLOYMENT_PROVENANCE_FIELD] = {
        **expected_seed,
        "checkpoint_id": str(getattr(checkpoint, "checkpoint_id", "")),
        "checkpoint_hash": str(getattr(checkpoint, "checkpoint_hash", "")),
    }
    with _REGISTRY_LOCK:
        _BOUND_CONTEXTS[str(context.run_id)] = weakref.ref(context)


def canonical_pending_approval_id(candidate_id: Optional[str]) -> Optional[str]:
    """Translate a receipt execution id to its server-originated pending approval id."""
    if not candidate_id:
        return candidate_id
    with _REGISTRY_LOCK:
        return _APPROVAL_REFERENCE_BY_EXECUTION.get(str(candidate_id), str(candidate_id))


def _get_bound_context(run_id: str) -> Optional[Any]:
    with _REGISTRY_LOCK:
        ref = _BOUND_CONTEXTS.get(str(run_id))
    if ref is None:
        return None
    context = ref()
    if context is None:
        with _REGISTRY_LOCK:
            _BOUND_CONTEXTS.pop(str(run_id), None)
    return context


def build_final_cmo_publish_parameters(context: Any, platform: str) -> Dict[str, Any]:
    """Validate durable Final CMO provenance and build approval-bound parameters."""
    final_output = getattr(context, "stage_outputs", {}).get("final_cmo")
    if not isinstance(final_output, dict):
        _fail("Final CMO output is missing.")
    if final_output.get("status") != "READY_FOR_DEPLOYMENT":
        _fail("Final CMO is not READY_FOR_DEPLOYMENT.")

    content = final_output.get("master_gtm_plan_markdown")
    if not isinstance(content, str) or not content.strip():
        _fail("Deployment-ready Final CMO output has no publishable Markdown content.")

    provenance = final_output.get(DEPLOYMENT_PROVENANCE_FIELD)
    if not isinstance(provenance, dict):
        _fail("Final CMO deployment provenance is missing.")

    expected_seed = _expected_seed(context, final_output)
    for key, value in expected_seed.items():
        if provenance.get(key) != value:
            _fail(f"Final CMO provenance field '{key}' does not match current semantic output/scope.")

    live_binding = getattr(context, "working_state", {}).get(DEPLOYMENT_BINDING_STATE_KEY)
    if live_binding != expected_seed:
        _fail("Live Final CMO deployment binding is missing or has been mutated.")

    checkpoint_id = str(provenance.get("checkpoint_id") or "")
    checkpoint_hash = str(provenance.get("checkpoint_hash") or "")
    if not checkpoint_id or not checkpoint_hash:
        _fail("Final CMO checkpoint identity/hash is missing.")

    matches = [cp for cp in getattr(context, "checkpoints", []) if str(getattr(cp, "checkpoint_id", "")) == checkpoint_id]
    if len(matches) != 1:
        _fail("Final CMO provenance must resolve to exactly one durable checkpoint.")
    checkpoint = matches[0]

    if str(getattr(checkpoint, "run_id", "")) != str(context.run_id):
        _fail("Checkpoint run scope does not match the active run.")
    if getattr(checkpoint, "business_id", None) != getattr(context, "business_id", None):
        _fail("Checkpoint business scope does not match the active run.")
    if getattr(checkpoint, "project_id", None) != getattr(context, "project_id", None):
        _fail("Checkpoint project scope does not match the active run.")
    if getattr(checkpoint, "chat_id", None) != getattr(context, "chat_id", None):
        _fail("Checkpoint chat scope does not match the active run.")
    if _enum_value(getattr(checkpoint, "stage", None)) != "FINAL_CMO":
        _fail("Deployment checkpoint is not a FINAL_CMO checkpoint.")
    if _enum_value(getattr(checkpoint, "status", None)) != "RUNNING":
        _fail("Deployment checkpoint was not created from an active successful run.")
    if _enum_value(getattr(checkpoint, "approval_state", None)) != "NOT_REQUIRED":
        _fail("Deployment checkpoint must precede the human publishing approval gate.")
    if "final_cmo" not in list(getattr(checkpoint, "completed_stages", []) or []):
        _fail("Deployment checkpoint does not commit a completed Final CMO stage.")
    if (getattr(checkpoint, "working_state_snapshot", {}) or {}).get(DEPLOYMENT_BINDING_STATE_KEY) != expected_seed:
        _fail("Checkpoint does not commit the expected Final CMO deployment binding.")
    if str(getattr(checkpoint, "checkpoint_hash", "")) != checkpoint_hash:
        _fail("Recorded checkpoint hash does not match Final CMO provenance.")
    if getattr(checkpoint, "calculate_checkpoint_hash")() != getattr(checkpoint, "checkpoint_hash", ""):
        _fail("Durable Final CMO checkpoint integrity verification failed.")

    platform_value = str(platform or "").strip()
    if not platform_value:
        _fail("Publishing platform is required.")

    return {
        "platform": platform_value,
        "content": content,
        "final_cmo_binding_id": expected_seed["binding_id"],
        "final_cmo_output_hash": expected_seed["output_hash"],
        "final_cmo_checkpoint_id": checkpoint_id,
        "final_cmo_checkpoint_hash": checkpoint_hash,
    }


def _deployment_model_post_init_hook(instance: Any) -> None:
    """Canonicalize legacy Runtime publish requests and receipt approval references."""
    cls = instance.__class__

    if cls.__name__ == "ExecutionReceipt" and cls.__module__ == "tools.receipts":
        if _enum_value(getattr(instance, "status", None)) == "APPROVAL_REQUIRED":
            execution_id = str(getattr(instance, "execution_id", "") or "")
            approval_reference = str(getattr(instance, "approval_reference", "") or "")
            if execution_id and approval_reference:
                with _REGISTRY_LOCK:
                    _APPROVAL_REFERENCE_BY_EXECUTION[execution_id] = approval_reference
        return

    if cls.__name__ != "ToolRequest" or cls.__module__ != "tools.tool_gateway":
        return
    if str(getattr(instance, "capability_id", "")).strip() != "social_publishing":
        return
    if str(getattr(instance, "agent_id", "")).strip().lower() != "cmo":
        return
    parameters = getattr(instance, "parameters", None)
    if not isinstance(parameters, dict):
        return
    if parameters.get("content") != LEGACY_RUNTIME_PUBLISH_PLACEHOLDER:
        return
    if set(parameters.keys()) - {"platform", "content"}:
        return

    run_id = str(getattr(instance, "run_id", "") or "")
    context = _get_bound_context(run_id)
    if context is None:
        _fail("No deployment-ready Final CMO context is registered for this runtime publish request.")
    instance.parameters = build_final_cmo_publish_parameters(
        context,
        str(parameters.get("platform") or ""),
    )


def clear_deployment_binding_registry_for_tests() -> None:
    """Hermetic test helper; production callers should never need this."""
    with _REGISTRY_LOCK:
        _BOUND_CONTEXTS.clear()
        _APPROVAL_REFERENCE_BY_EXECUTION.clear()


register_model_post_init_hook(_deployment_model_post_init_hook)
