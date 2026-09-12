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
_APPROVED_DEPLOYMENT_AUTHORIZATION_STATUSES = frozenset({"APPROVED", "APPROVED_WITH_CONDITIONS"})

_BOUND_CONTEXTS: Dict[str, weakref.ReferenceType[Any]] = {}
_APPROVAL_REFERENCE_BY_EXECUTION: Dict[str, str] = {}
_REGISTRY_LOCK = RLock()


def _fail(detail: str) -> None:
    raise RuntimeError(f"{DEPLOYMENT_ERROR_PREFIX}: {detail}")


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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


def _deployment_approved(output: Dict[str, Any]) -> bool:
    """Return True only when Final CMO authorization is explicitly deployment-approved."""
    approval_status = str(output.get("approval_status") or "").strip().upper()
    claim_audit = output.get("claim_audit")
    if not isinstance(claim_audit, dict):
        return False
    audit_status = str(claim_audit.get("authorization_status") or "").strip().upper()
    return (
        approval_status in _APPROVED_DEPLOYMENT_AUTHORIZATION_STATUSES
        and audit_status == approval_status
    )


def _binding_id(run_id: str, output_hash: str) -> str:
    raw = f"FINAL_CMO_DEPLOYMENT:{run_id}:{output_hash}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    return f"FCMO-BIND-{digest[:24]}"


def _expected_seed(context: Any, output: Dict[str, Any]) -> Dict[str, Any]:
    output_hash = final_cmo_semantic_output_hash(output)
    content = output.get("master_gtm_plan_markdown")
    content_hash = _sha256_text(content) if isinstance(content, str) else ""
    manifest = {
        "artifact_type": "FINAL_CMO_MASTER_GTM_PLAN_MARKDOWN",
        "hash_algorithm": "sha256",
        "content_hash": content_hash,
        "semantic_output_hash": output_hash,
    }
    manifest_hash = _sha256_text(
        json.dumps(
            manifest,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return {
        "run_id": str(context.run_id),
        "business_id": getattr(context, "business_id", None),
        "project_id": getattr(context, "project_id", None),
        "chat_id": getattr(context, "chat_id", None),
        "binding_id": _binding_id(str(context.run_id), output_hash),
        "status": "READY_FOR_DEPLOYMENT",
        "deployment_approved": _deployment_approved(output),
        "output_hash": output_hash,
        "content_hash": content_hash,
        "manifest_hash": manifest_hash,
    }


def _assert_registry_context_compatible(context: Any) -> None:
    """Fail closed if a different live context already owns this run id."""
    run_id = str(getattr(context, "run_id", "") or "")
    if not run_id:
        _fail("RuntimeContext has no authoritative run_id for deployment binding.")

    with _REGISTRY_LOCK:
        existing_ref = _BOUND_CONTEXTS.get(run_id)
        if existing_ref is None:
            return
        existing = existing_ref()
        if existing is None:
            _BOUND_CONTEXTS.pop(run_id, None)
            return
        if existing is not context:
            _fail("A different live RuntimeContext is already registered for this run_id.")


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
    if not _deployment_approved(output):
        _fail("Deployment-ready Final CMO output is not explicitly deployment-approved.")

    _assert_registry_context_compatible(context)

    # Already committed. Later WAITING/RUNNING approval checkpoints must not
    # silently rebind the deployment artifact.
    if isinstance(output.get(DEPLOYMENT_PROVENANCE_FIELD), dict):
        return False

    expected_seed = _expected_seed(context, output)
    if expected_seed.get("deployment_approved") is not True:
        _fail("Final CMO deployment approval could not be bound into checkpoint provenance.")
    getattr(context, "working_state")[DEPLOYMENT_BINDING_STATE_KEY] = expected_seed
    return True


def register_final_cmo_checkpoint(context: Any, checkpoint: Any, prepared: bool) -> None:
    """Attach derived checkpoint provenance and register the live bound context."""
    if not prepared:
        return

    _assert_registry_context_compatible(context)

    output = getattr(context, "stage_outputs", {}).get("final_cmo")
    if not isinstance(output, dict) or output.get("status") != "READY_FOR_DEPLOYMENT":
        _fail("Final CMO changed before deployment checkpoint registration.")
    if not _deployment_approved(output):
        _fail("Final CMO authorization changed before deployment checkpoint registration.")

    expected_seed = _expected_seed(context, output)
    if expected_seed.get("deployment_approved") is not True:
        _fail("Final CMO deployment approval is not explicitly true.")
    snapshot = getattr(checkpoint, "working_state_snapshot", {}) or {}
    if snapshot.get(DEPLOYMENT_BINDING_STATE_KEY) != expected_seed:
        _fail("Final CMO deployment seed was not committed by the checkpoint.")
    if _enum_value(getattr(checkpoint, "stage", None)) != "FINAL_CMO":
        _fail("Deployment checkpoint is not a FINAL_CMO checkpoint.")
    if _enum_value(getattr(checkpoint, "status", None)) != "RUNNING":
        _fail("Deployment checkpoint was not created from an active successful run.")
    if getattr(checkpoint, "calculate_checkpoint_hash")() != getattr(checkpoint, "checkpoint_hash", ""):
        _fail("Durable Final CMO checkpoint integrity verification failed.")

    provenance = {
        **expected_seed,
        "checkpoint_id": str(getattr(checkpoint, "checkpoint_id", "")),
        "checkpoint_hash": str(getattr(checkpoint, "checkpoint_hash", "")),
    }
    run_id = str(context.run_id)
    with _REGISTRY_LOCK:
        _assert_registry_context_compatible(context)
        output[DEPLOYMENT_PROVENANCE_FIELD] = provenance
        _BOUND_CONTEXTS[run_id] = weakref.ref(context)


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
    if not _deployment_approved(final_output):
        _fail("Final CMO is not explicitly deployment-approved.")

    content = final_output.get("master_gtm_plan_markdown")
    if not isinstance(content, str) or not content.strip():
        _fail("Deployment-ready Final CMO output has no publishable Markdown content.")

    provenance = final_output.get(DEPLOYMENT_PROVENANCE_FIELD)
    if not isinstance(provenance, dict):
        _fail("Final CMO deployment provenance is missing.")
    if provenance.get("deployment_approved") is not True:
        _fail("Final CMO provenance does not carry deployment_approved=true.")

    expected_seed = _expected_seed(context, final_output)
    if expected_seed.get("deployment_approved") is not True:
        _fail("Current Final CMO authorization is no longer deployment-approved.")
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
        "final_cmo_content_hash": expected_seed["content_hash"],
        "final_cmo_manifest_hash": expected_seed["manifest_hash"],
        "final_cmo_checkpoint_id": checkpoint_id,
        "final_cmo_checkpoint_hash": checkpoint_hash,
        "deployment_approved": True,
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
    if run_id != str(getattr(context, "run_id", "") or ""):
        _fail("Runtime publish request run scope does not match registered Final CMO context.")
    for field_name in ("business_id", "project_id", "chat_id"):
        if getattr(instance, field_name, None) != getattr(context, field_name, None):
            _fail(
                f"Runtime publish request {field_name} scope does not match registered Final CMO context."
            )
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
