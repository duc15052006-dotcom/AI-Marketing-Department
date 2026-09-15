"""Read-only platform observability and inspection surfaces.

The inspector deliberately aggregates existing authorities instead of creating a
second logging or telemetry database. It never dispatches tools, refreshes MCP
servers, resolves secrets, mutates jobs, or retries recovered work.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional

from governance.redaction import sanitize_sensitive_payload


class InspectorError(RuntimeError):
    """Base inspector error."""


class InspectorUnavailableError(InspectorError):
    """Raised when a required read authority was not configured."""


class InspectorNotFoundError(InspectorError):
    """Raised when the requested observable entity does not exist."""


class InspectorScopeError(InspectorError):
    """Raised when tenant scope cannot be proven to match exactly."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _scope_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class PlatformInspector:
    """Read-only aggregator over durable platform authorities.

    Run-level inspection is fail-closed on business scope. The durable job is the
    scope anchor; every receipt and execution intent for the run must match that
    exact business scope or inspection aborts with ``InspectorScopeError``.

    ``platform_snapshot`` is intentionally metadata-only. It does not expose MCP
    endpoints/headers, plugin metadata, capability schemas, execution payloads,
    or secret values, and it never performs network discovery.
    """

    def __init__(
        self,
        *,
        job_repository: Optional[Any] = None,
        receipt_repository: Optional[Any] = None,
        dynamic_gateway: Optional[Any] = None,
    ) -> None:
        self.job_repository = job_repository
        self.receipt_repository = receipt_repository
        self.dynamic_gateway = dynamic_gateway

    @staticmethod
    def _safe(payload: Any) -> Any:
        return sanitize_sensitive_payload(payload)

    @staticmethod
    def _assert_scope(expected_business_id: Optional[str], actual_business_id: Optional[str], source: str) -> None:
        if _scope_key(expected_business_id) != _scope_key(actual_business_id):
            raise InspectorScopeError(
                f"INSPECTOR_SCOPE_MISMATCH: {source} is not bound to the requested business scope"
            )

    @staticmethod
    def _job_projection(job: Any) -> Dict[str, Any]:
        return {
            "run_id": job.run_id,
            "objective": job.objective,
            "business_id": job.business_id,
            "project_id": job.project_id,
            "chat_id": job.chat_id,
            "status": job.status,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error": job.error,
            "recovery_reason": job.recovery_reason,
            "artifact_hash": job.artifact_hash,
            "attempt_count": job.attempt_count,
            "updated_at": job.updated_at,
        }

    @staticmethod
    def _receipt_projection(receipt: Any) -> Dict[str, Any]:
        return {
            "execution_id": receipt.execution_id,
            "run_id": receipt.run_id,
            "agent_id": receipt.agent_id,
            "capability_id": receipt.capability_id,
            "provider": receipt.provider,
            "request_hash": receipt.request_hash,
            "result_hash": receipt.result_hash,
            "started_at": _iso(receipt.started_at),
            "completed_at": _iso(receipt.completed_at),
            "status": _enum_value(receipt.status),
            "execution_mode": _enum_value(receipt.execution_mode),
            "error_class": receipt.error_class,
            "error_message": receipt.error_message,
            "approval_reference": receipt.approval_reference,
            "business_id": receipt.business_id,
            "project_id": receipt.project_id,
            "chat_id": receipt.chat_id,
            "artifact_references": list(receipt.artifact_references or []),
            "cost_or_token_usage": dict(receipt.cost_or_token_usage or {}),
        }

    @staticmethod
    def _intent_projection(intent: Any, assessment: Optional[Any] = None) -> Dict[str, Any]:
        projection = {
            "intent_id": intent.intent_id,
            "request_id": intent.request_id,
            "run_id": intent.run_id,
            "agent_id": intent.agent_id,
            "capability_id": intent.capability_id,
            "provider": intent.provider,
            "request_hash": intent.request_hash,
            "state": _enum_value(intent.state),
            "business_id": intent.business_id,
            "project_id": intent.project_id,
            "chat_id": intent.chat_id,
            "approval_reference": intent.approval_reference,
            "dispatch_count": intent.dispatch_count,
            "receipt_execution_id": intent.receipt_execution_id,
            "last_error_class": intent.last_error_class,
            "last_error_message": intent.last_error_message,
            "created_at": intent.created_at,
            "updated_at": intent.updated_at,
        }
        if assessment is not None:
            projection["reconciliation"] = {
                "outcome": _enum_value(assessment.outcome),
                "receipt_execution_id": assessment.receipt_execution_id,
                "reason": assessment.reason,
            }
        return projection

    def list_runs(
        self,
        *,
        business_id: Optional[str],
        statuses: Optional[Iterable[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List minimal run metadata for one exact business scope."""
        if self.job_repository is None:
            raise InspectorUnavailableError("JOB_REPOSITORY_REQUIRED: run listing requires durable job storage")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > 500:
            raise ValueError("INVALID_INSPECTOR_LIMIT: limit must be an integer from 1 to 500")

        jobs = self.job_repository.list_jobs(statuses=statuses)
        target_scope = _scope_key(business_id)
        visible: List[Dict[str, Any]] = []
        for job in jobs:
            if _scope_key(job.business_id) != target_scope:
                continue
            visible.append(
                {
                    "run_id": job.run_id,
                    "status": job.status,
                    "project_id": job.project_id,
                    "chat_id": job.chat_id,
                    "created_at": job.created_at,
                    "started_at": job.started_at,
                    "completed_at": job.completed_at,
                    "attempt_count": job.attempt_count,
                    "recovery_required": job.status == "RECOVERY_REQUIRED",
                }
            )
            if len(visible) >= limit:
                break
        return self._safe(visible)

    def inspect_run(self, *, run_id: str, business_id: Optional[str]) -> Dict[str, Any]:
        """Return a scope-checked, redacted run timeline without mutating state."""
        if self.job_repository is None:
            raise InspectorUnavailableError("JOB_REPOSITORY_REQUIRED: run inspection requires durable job storage")
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            raise ValueError("RUN_ID_REQUIRED: run inspection requires run_id")

        job = self.job_repository.get_job(normalized_run_id)
        if job is None:
            raise InspectorNotFoundError("RUN_NOT_FOUND: requested run does not exist")
        self._assert_scope(business_id, job.business_id, "job")

        events = list(self.job_repository.list_events(normalized_run_id))
        checkpoints = list(self.job_repository.list_checkpoints(normalized_run_id))
        receipts: List[Any] = []
        intents: List[Any] = []
        intent_views: List[Dict[str, Any]] = []

        if self.receipt_repository is not None:
            receipts = list(self.receipt_repository.list_receipts_for_run(normalized_run_id))
            intents = list(self.receipt_repository.list_execution_intents_for_run(normalized_run_id))

            for receipt in receipts:
                self._assert_scope(job.business_id, receipt.business_id, "execution receipt")
            for intent in intents:
                self._assert_scope(job.business_id, intent.business_id, "execution intent")
                assessment = self.receipt_repository.assess_execution_intent(intent.intent_id)
                intent_views.append(self._intent_projection(intent, assessment))

        receipt_views = [self._receipt_projection(receipt) for receipt in receipts]
        timeline: List[Dict[str, Any]] = []

        for event in events:
            timeline.append(
                {
                    "timestamp": event.get("created_at"),
                    "source": "job_event",
                    "type": event.get("event_type"),
                    "status": event.get("status"),
                    "message": event.get("message"),
                    "id": event.get("event_id"),
                }
            )
        for checkpoint in checkpoints:
            timeline.append(
                {
                    "timestamp": checkpoint.get("timestamp") or checkpoint.get("created_at"),
                    "source": "checkpoint",
                    "type": "CHECKPOINT",
                    "status": _enum_value(checkpoint.get("status")),
                    "id": checkpoint.get("checkpoint_id"),
                }
            )
        for view in intent_views:
            timeline.append(
                {
                    "timestamp": view.get("updated_at") or view.get("created_at"),
                    "source": "execution_intent",
                    "type": view.get("state"),
                    "status": view.get("reconciliation", {}).get("outcome"),
                    "capability_id": view.get("capability_id"),
                    "id": view.get("intent_id"),
                }
            )
        for view in receipt_views:
            timeline.append(
                {
                    "timestamp": view.get("completed_at") or view.get("started_at"),
                    "source": "execution_receipt",
                    "type": "TOOL_EXECUTION",
                    "status": view.get("status"),
                    "capability_id": view.get("capability_id"),
                    "id": view.get("execution_id"),
                }
            )

        timeline.sort(
            key=lambda item: (
                str(item.get("timestamp") or ""),
                str(item.get("source") or ""),
                str(item.get("id") or ""),
            )
        )

        snapshot = {
            "generated_at": _utc_now_iso(),
            "run": self._job_projection(job),
            "events": events,
            "checkpoints": checkpoints,
            "execution_intents": intent_views,
            "execution_receipts": receipt_views,
            "timeline": timeline,
            "source_availability": {
                "job_repository": True,
                "receipt_repository": self.receipt_repository is not None,
            },
            "redaction_applied": True,
        }
        return self._safe(snapshot)

    def platform_snapshot(self) -> Dict[str, Any]:
        """Return safe platform metadata without probing external services."""
        snapshot: Dict[str, Any] = {
            "generated_at": _utc_now_iso(),
            "redaction_applied": True,
            "network_probe_performed": False,
            "sources": {
                "job_repository": self.job_repository is not None,
                "receipt_repository": self.receipt_repository is not None,
                "dynamic_gateway": self.dynamic_gateway is not None,
            },
        }

        if self.job_repository is not None:
            jobs = list(self.job_repository.list_jobs())
            counts = Counter(str(job.status) for job in jobs)
            snapshot["jobs"] = {
                "total": len(jobs),
                "by_status": dict(sorted(counts.items())),
                "recovery_required": counts.get("RECOVERY_REQUIRED", 0),
            }

        if self.receipt_repository is not None:
            snapshot["receipt_store"] = {
                "configured": True,
                "durable": bool(getattr(self.receipt_repository, "durable", False)),
            }

        if self.dynamic_gateway is not None:
            registry = self.dynamic_gateway.registry
            snapshot["capability_registry"] = registry.snapshot()
            snapshot["capabilities"] = [
                {
                    "capability_id": descriptor.capability_id,
                    "provider": descriptor.provider,
                    "category": _enum_value(descriptor.category),
                    "risk_level": _enum_value(descriptor.risk_level),
                    "availability": descriptor.availability,
                    "human_approval_required": bool(descriptor.human_approval_required),
                }
                for descriptor in self.dynamic_gateway.list_capabilities()
            ]

            active_plugin_ids = registry.list_dynamic_capability_ids("plugins")
            plugins = []
            for record in self.dynamic_gateway.plugin_registry.list_plugins():
                prefix = f"plugin.{record.manifest.plugin_id}."
                plugins.append(
                    {
                        "plugin_id": record.manifest.plugin_id,
                        "name": record.manifest.name,
                        "version": record.manifest.version,
                        "state": _enum_value(record.state),
                        "declared_tool_count": len(record.manifest.tools),
                        "active_capability_count": sum(
                            1 for capability_id in active_plugin_ids if capability_id.startswith(prefix)
                        ),
                    }
                )
            snapshot["plugins"] = plugins

            mcp_servers = []
            for config in self.dynamic_gateway.mcp_registry.list_servers():
                source = f"mcp:{config.server_id}"
                mcp_servers.append(
                    {
                        "server_id": config.server_id,
                        "configuration_state": "ENABLED" if config.enabled else "DISABLED",
                        "protocol_version": config.protocol_version,
                        "timeout_seconds": config.timeout_seconds,
                        "discovered_capability_count": len(
                            registry.list_dynamic_capability_ids(source)
                        ),
                    }
                )
            snapshot["mcp_servers"] = mcp_servers

        return self._safe(snapshot)
