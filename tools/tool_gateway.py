"""Universal Tool Gateway (Phase 5.1).

The single unified access point for all external and operational capabilities
across the Five-Agent Department:
- Decouples Five-Agent Brain from external tools and platforms
- Strict RBAC permission enforcement
- Human Approval Gate for high-risk / publishing / financial actions
- Side-effect-safe retry, timeout handling, and error normalization
- Generates immutable ExecutionReceipts for every invocation
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field

from tools.adapters import (
    AnalyticsAdapter,
    BaseCapabilityAdapter,
    CreativeTextAdapter,
    FileStorageAdapter,
    HttpAdapter,
    MediaCreationAdapter,
    PublishingAdapter,
    SearchAdapter,
)
from tools.capabilities import CapabilityCategory, CapabilityDescriptor, CapabilityRegistry, PermissionLevel, RiskLevel
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus, _safe_approval_reference
from tools.security import PolicyDecision, PolicyEngine

logger = logging.getLogger("tool_gateway")


class ToolRequest(BaseModel):
    """Standardized tool invocation envelope passed into the Tool Gateway."""
    request_id: str = Field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:12].upper()}")
    run_id: str = Field(default="RUN-DEFAULT-001", description="Campaign or workflow execution run ID")
    agent_id: str = Field(..., description="Requesting agent: 'cmo' | 'intelligence' | 'strategist' | 'creative' | 'performance'")
    capability_id: str = Field(..., description="Target capability name, e.g. 'web_search', 'social_publishing'")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Execution parameters")
    approval_token: Optional[str] = Field(default=None, description="Human approval authorization token if required")
    timeout_seconds: Optional[float] = Field(default=None, description="Optional override for execution timeout")
    business_id: Optional[str] = Field(default=None, description="Tenant/business scope")
    project_id: Optional[str] = Field(default=None, description="Associated workspace project ID")
    chat_id: Optional[str] = Field(default=None, description="Associated chat session ID")

    def calculate_request_hash(self) -> str:
        """Compute SHA-256 hash of the request parameters."""
        raw = f"{self.run_id}:{self.agent_id}:{self.capability_id}:{json.dumps(self.parameters, sort_keys=True, ensure_ascii=False)}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ToolGateway:
    """Central gateway orchestrating all capability executions with policy, safety, and receipts."""

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        receipt_repository: Optional[ExecutionReceiptRepository] = None,
    ) -> None:
        if capability_registry is None:
            raise ValueError("ToolGateway requires an explicit CapabilityRegistry instance. Pass capability_registry= to the constructor.")
        self.registry = capability_registry
        self.policy_engine = policy_engine or PolicyEngine()
        self.receipt_repository = receipt_repository or ExecutionReceiptRepository()
        self._adapters: Dict[str, BaseCapabilityAdapter] = {}
        self._register_default_adapters()

    def register_adapter(self, adapter: BaseCapabilityAdapter, aliases: Optional[List[str]] = None) -> None:
        """Register a provider adapter and optional capability provider aliases."""
        self._adapters[adapter.adapter_name.lower()] = adapter
        if aliases:
            for alias in aliases:
                self._adapters[alias.lower()] = adapter
        logger.info(f"Registered tool adapter: {adapter.adapter_name} (aliases: {aliases or []})")

    def bind_adapter_alias(self, alias: str, adapter: BaseCapabilityAdapter) -> None:
        """Explicitly bind a capability provider alias to an adapter instance."""
        self._adapters[alias.lower()] = adapter
        logger.info(f"Bound tool adapter alias '{alias}' to adapter: {adapter.adapter_name}")

    def get_adapter(self, adapter_name: str) -> Optional[BaseCapabilityAdapter]:
        """Retrieve registered adapter by name."""
        return self._adapters.get(adapter_name.lower())

    def _register_default_adapters(self) -> None:
        """Load default provider-neutral adapters."""
        self.register_adapter(SearchAdapter())
        self.register_adapter(HttpAdapter())
        self.register_adapter(CreativeTextAdapter())
        self.register_adapter(MediaCreationAdapter(name="image_gen_adapter"))
        self.register_adapter(MediaCreationAdapter(name="image_edit_adapter"))
        self.register_adapter(MediaCreationAdapter(name="video_gen_adapter"))
        self.register_adapter(MediaCreationAdapter(name="video_edit_adapter"))
        self.register_adapter(PublishingAdapter(name="social_publish_adapter"))
        self.register_adapter(PublishingAdapter(name="schedule_adapter"))
        self.register_adapter(PublishingAdapter(name="ad_platform_adapter"))
        self.register_adapter(AnalyticsAdapter(name="analytics_adapter"))
        self.register_adapter(AnalyticsAdapter(name="kpi_calc_adapter"))
        self.register_adapter(AnalyticsAdapter(name="attribution_adapter"))
        self.register_adapter(AnalyticsAdapter(name="stats_analysis_adapter"))
        self.register_adapter(FileStorageAdapter())
        self.register_adapter(AnalyticsAdapter(name="data_retrieval_adapter"))
        self.register_adapter(FileStorageAdapter())  # file_io_adapter
        # Alias for db_storage_adapter and export_adapter
        class DBAdapter(FileStorageAdapter):
            @property
            def adapter_name(self) -> str:
                return "db_storage_adapter"
        class ExportAdapter(FileStorageAdapter):
            @property
            def adapter_name(self) -> str:
                return "export_adapter"
        self.register_adapter(DBAdapter())
        self.register_adapter(ExportAdapter())

    @staticmethod
    def _is_consequential_capability(cap: CapabilityDescriptor) -> bool:
        """Return whether dispatch can produce externally consequential side effects.

        Retry safety is a property of the capability itself, not of whether an
        approval token happened to be supplied on this specific request.
        """
        return bool(
            cap.human_approval_required
            or cap.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
            or cap.category == CapabilityCategory.PUBLISH
            or PermissionLevel.FINANCIAL_OR_HIGH_RISK in cap.required_permissions
            or PermissionLevel.PUBLISH in cap.required_permissions
            or PermissionLevel.EXTERNAL_WRITE in cap.required_permissions
        )

    @staticmethod
    def _classify_retryable_exception(exc: BaseException) -> Optional[str]:
        """Map only clearly transient built-in exception classes to retry codes.

        Unknown adapter exceptions fail closed. They are never made implicitly
        retryable merely because a capability has retries configured.
        """
        if isinstance(exc, TimeoutError):
            return "TIMEOUT"
        if isinstance(exc, ConnectionError):
            return "NETWORK_ERROR"
        return None

    @staticmethod
    def _resolve_execution_mode(
        adapter: BaseCapabilityAdapter,
        capability_id: str,
        adapter_result: Optional[Any] = None,
    ) -> ExecutionMode:
        """Resolve truthful execution provenance for both success and failure receipts.

        Adapters that multiplex REAL/MOCK/SANDBOX capabilities may expose
        ``execution_mode_for(capability_id)``. That capability-level authority
        takes precedence over an AdapterResult default so failed REAL calls are
        never mislabeled MOCK. Unknown/legacy adapters fail closed to the result's
        explicit mode, then MOCK.
        """
        resolver = getattr(adapter, "execution_mode_for", None)
        if callable(resolver):
            try:
                resolved = resolver(capability_id)
                if isinstance(resolved, ExecutionMode):
                    return resolved
                if isinstance(resolved, str):
                    return ExecutionMode(resolved.strip().upper())
            except Exception:
                pass

        if adapter_result is not None:
            raw_mode = getattr(adapter_result, "execution_mode", None)
            if isinstance(raw_mode, ExecutionMode):
                return raw_mode
            if isinstance(raw_mode, str):
                try:
                    return ExecutionMode(raw_mode.strip().upper())
                except Exception:
                    pass

        return ExecutionMode.MOCK

    def _existing_consequential_request_result(
        self,
        *,
        request: ToolRequest,
        adapter: BaseCapabilityAdapter,
        request_hash: str,
        start_time: datetime,
        execution_mode: ExecutionMode,
    ) -> Optional[ExecutionReceipt]:
        """Return durable evidence for a previously journaled request without replaying I/O.

        ``request_id`` is a one-shot idempotency authority within a run for
        consequential effects. A retry may observe the existing receipt, but it
        may never create another external dispatch for the same durable request.
        """
        matching = [
            intent
            for intent in self.receipt_repository.list_execution_intents_for_run(request.run_id)
            if intent.request_id == request.request_id
        ]
        if not matching:
            return None

        completed_time = datetime.now(timezone.utc)
        if len(matching) != 1:
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=adapter.adapter_name,
                request_hash=request_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=ExecutionStatus.ERROR,
                execution_mode=execution_mode,
                error_class="CONSEQUENTIAL_REQUEST_ID_MULTIPLE_INTENTS",
                error_message=(
                    "CONSEQUENTIAL_REQUEST_ID_MULTIPLE_INTENTS: Durable journal contains multiple intents "
                    "for the same run_id/request_id; replay is blocked pending reconciliation."
                ),
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
            return self.receipt_repository.save_receipt(receipt)

        existing = matching[0]
        binding_matches = (
            existing.agent_id.lower() == request.agent_id.lower()
            and existing.capability_id.lower() == request.capability_id.lower()
            and existing.provider.lower() == adapter.adapter_name.lower()
            and existing.request_hash == request_hash
            and existing.execution_mode == execution_mode
            and existing.business_id == request.business_id
            and existing.project_id == request.project_id
            and existing.chat_id == request.chat_id
        )
        if not binding_matches:
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=adapter.adapter_name,
                request_hash=request_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=ExecutionStatus.ERROR,
                execution_mode=execution_mode,
                error_class="CONSEQUENTIAL_REQUEST_ID_BINDING_CONFLICT",
                error_message=(
                    "CONSEQUENTIAL_REQUEST_ID_BINDING_CONFLICT: request_id is already bound to different "
                    "immutable consequential authority; provider replay is forbidden."
                ),
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
            return self.receipt_repository.save_receipt(receipt)

        if existing.receipt_execution_id:
            durable_receipt = self.receipt_repository.get_receipt(existing.receipt_execution_id)
            if durable_receipt is None:
                raise RuntimeError(
                    "CONSEQUENTIAL_REQUEST_DURABLE_RECEIPT_MISSING: "
                    f"intent_id={existing.intent_id} execution_id={existing.receipt_execution_id}"
                )
            return durable_receipt

        assessment = self.receipt_repository.assess_execution_intent(existing.intent_id)
        outcome = getattr(assessment.outcome, "value", str(assessment.outcome))
        if outcome == "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME":
            error_class = "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME"
            error_message = (
                "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME: durable evidence shows that dispatch may already have "
                "reached the provider; replay of the same request_id is forbidden."
            )
        else:
            error_class = "CONSEQUENTIAL_REQUEST_REPLAY_BLOCKED"
            error_message = (
                "CONSEQUENTIAL_REQUEST_REPLAY_BLOCKED: request_id already has durable intent evidence "
                f"({outcome}); a second provider dispatch is forbidden."
            )

        receipt = ExecutionReceipt(
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id=request.capability_id,
            provider=adapter.adapter_name,
            request_hash=request_hash,
            started_at=start_time,
            completed_at=completed_time,
            status=ExecutionStatus.ERROR,
            execution_mode=execution_mode,
            error_class=error_class,
            error_message=error_message,
            approval_reference=existing.approval_reference,
            business_id=request.business_id,
            project_id=request.project_id,
            chat_id=request.chat_id,
        )
        return self.receipt_repository.save_receipt(receipt)

    def execute(self, request: ToolRequest) -> ExecutionReceipt:
        """Execute a tool capability with complete governance, permissions, and receipt creation."""
        start_time = datetime.now(timezone.utc)
        req_hash = request.calculate_request_hash()

        # 1. Capability Discovery
        cap = self.registry.get_capability(request.capability_id)
        if not cap:
            completed_time = datetime.now(timezone.utc)
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider="gateway",
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=ExecutionStatus.ERROR,
                error_class="CAPABILITY_NOT_FOUND",
                error_message=f"Capability '{request.capability_id}' is not registered in CapabilityRegistry.",
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
            return self.receipt_repository.save_receipt(receipt)

        # 2. Permission & Safety Policy Gate
        decision = self.policy_engine.evaluate(
            agent_id=request.agent_id,
            capability=cap,
            approval_token=request.approval_token,
            run_id=request.run_id,
            business_id=request.business_id,
            parameters=request.parameters,
        )
        if not decision.allowed:
            completed_time = datetime.now(timezone.utc)
            status = ExecutionStatus.APPROVAL_REQUIRED if decision.requires_human_approval else ExecutionStatus.BLOCKED
            err_class = decision.error_code or ("HUMAN_APPROVAL_REQUIRED" if decision.requires_human_approval else "PERMISSION_DENIED")
            appr_ref = request.approval_token
            if decision.requires_human_approval and not appr_ref:
                pending_rec = self.policy_engine.create_pending_approval(
                    capability_id=request.capability_id,
                    parameters=request.parameters,
                    run_id=request.run_id,
                    business_id=request.business_id,
                    scope="",
                    risk_level=cap.risk_level,
                )
                appr_ref = pending_rec.pending_approval_id

            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=cap.provider,
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=status,
                error_class=err_class,
                error_message=decision.reason,
                approval_reference=appr_ref,
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
            return self.receipt_repository.save_receipt(receipt)

        # 3. Retrieve Provider Adapter
        adapter = self.get_adapter(cap.provider)
        if adapter is None:
            completed_time = datetime.now(timezone.utc)
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=cap.provider,
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=ExecutionStatus.ERROR,
                error_class="PROVIDER_NOT_CONFIGURED",
                error_message=f"Provider adapter '{cap.provider}' is not registered with ToolGateway.",
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
            return self.receipt_repository.save_receipt(receipt)

        # 4. Durable request-id idempotency and atomic one-shot approval claim.
        cap_is_consequential = self._is_consequential_capability(cap)
        is_consequential = bool(request.approval_token and cap_is_consequential)
        approval_reference = _safe_approval_reference(request.approval_token)
        adapter_execution_mode = self._resolve_execution_mode(adapter, cap.capability_id)

        if cap_is_consequential:
            existing_result = self._existing_consequential_request_result(
                request=request,
                adapter=adapter,
                request_hash=req_hash,
                start_time=start_time,
                execution_mode=adapter_execution_mode,
            )
            if existing_result is not None:
                return existing_result

        if is_consequential:
            claimed = self.policy_engine.claim_approval(request.approval_token)
            if not claimed:
                completed_time = datetime.now(timezone.utc)
                receipt = ExecutionReceipt(
                    run_id=request.run_id,
                    agent_id=request.agent_id,
                    capability_id=request.capability_id,
                    provider=adapter.adapter_name,
                    request_hash=req_hash,
                    started_at=start_time,
                    completed_at=completed_time,
                    status=ExecutionStatus.APPROVAL_REQUIRED,
                    error_class="APPROVAL_ALREADY_CLAIMED",
                    error_message="APPROVAL_ALREADY_CLAIMED: Approval token has already been claimed or consumed for execution.",
                    approval_reference=approval_reference,
                    business_id=request.business_id,
                    project_id=request.project_id,
                    chat_id=request.chat_id,
                )
                return self.receipt_repository.save_receipt(receipt)

        # 5. Execute Invocation with Side-Effect-Safe Timeout & Retries
        timeout = request.timeout_seconds or cap.timeout_policy
        max_retries = max(0, int(cap.retry_policy.get("max_retries", 0) or 0))
        retryable_errors = set(cap.retry_policy.get("retryable_errors", []))
        try:
            backoff_seconds = float(cap.retry_policy.get("backoff_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            backoff_seconds = 0.0
        backoff_seconds = min(max(backoff_seconds, 0.0), 10.0)

        adapter_res = None
        last_exc: Optional[BaseException] = None
        exception_error_code: Optional[str] = None
        ambiguous_external_outcome = False
        execution_intent = None

        try:
            if cap_is_consequential:
                execution_intent = self.receipt_repository.prepare_execution_intent(
                    request_id=request.request_id,
                    run_id=request.run_id,
                    agent_id=request.agent_id,
                    capability_id=request.capability_id,
                    provider=adapter.adapter_name,
                    request_hash=req_hash,
                    execution_mode=adapter_execution_mode,
                    business_id=request.business_id,
                    project_id=request.project_id,
                    chat_id=request.chat_id,
                    approval_reference=approval_reference,
                )
                self.receipt_repository.mark_execution_intent_dispatching(
                    execution_intent.intent_id
                )

            for attempt in range(max_retries + 1):
                try:
                    adapter_res = adapter.execute(
                        capability_id=cap.capability_id,
                        parameters=request.parameters,
                        timeout_seconds=timeout,
                        run_id=request.run_id,
                        business_id=request.business_id or "",
                        project_id=request.project_id or "",
                    )
                    last_exc = None
                    exception_error_code = None
                except Exception as exc:
                    adapter_res = None
                    last_exc = exc
                    exception_error_code = self._classify_retryable_exception(exc)

                    # Once a consequential dispatch begins, a thrown exception
                    # leaves remote acceptance ambiguous. Re-dispatching could
                    # duplicate publishing, scheduling, or financial side effects.
                    if cap_is_consequential:
                        ambiguous_external_outcome = True
                        break

                    # Safe/read-only operations retry only explicitly classified
                    # transient exception types and only when policy permits it.
                    if exception_error_code not in retryable_errors:
                        break
                    if attempt >= max_retries:
                        break
                    if backoff_seconds > 0:
                        time.sleep(backoff_seconds)
                    continue

                if adapter_res.success:
                    break

                # Consequential capabilities are one-dispatch per gateway call.
                # Even a structured transient error can be ambiguous if the
                # provider reports failure after an external action was accepted.
                if cap_is_consequential:
                    break

                # Structured failures are retryable only when the adapter's
                # normalized error code is explicitly declared by the capability.
                if adapter_res.error_code not in retryable_errors:
                    break
                if attempt >= max_retries:
                    break
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds)
        finally:
            if is_consequential:
                self.policy_engine.consume_approval(request.approval_token)

        completed_time = datetime.now(timezone.utc)

        # 6. Assemble Receipt
        if adapter_res and adapter_res.success:
            mode = self._resolve_execution_mode(adapter, cap.capability_id, adapter_res)
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=adapter.adapter_name,
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=ExecutionStatus.SUCCESS,
                execution_mode=mode,
                data=adapter_res.data,
                cost_or_token_usage=adapter_res.cost_or_tokens,
                artifact_references=adapter_res.artifact_refs,
                approval_reference=approval_reference,
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
                observation_record=adapter_res.observation_record,
            )
        else:
            if ambiguous_external_outcome:
                err_code = "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME"
                err_msg = (
                    "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME: The external action may have been accepted "
                    "before execution raised an exception; automatic retry was suppressed to prevent "
                    "duplicate side effects."
                )
            elif adapter_res is not None:
                err_code = adapter_res.error_code or "EXECUTION_ERROR"
                err_msg = adapter_res.error_message or "Tool adapter execution failed."
            else:
                err_code = exception_error_code or "EXECUTION_EXCEPTION"
                err_msg = str(last_exc) if last_exc is not None else "Tool adapter execution failed."

            status = ExecutionStatus.TIMEOUT if err_code == "TIMEOUT" else ExecutionStatus.ERROR
            mode = self._resolve_execution_mode(adapter, cap.capability_id, adapter_res)
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=adapter.adapter_name,
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=status,
                execution_mode=mode,
                error_class=err_code,
                error_message=err_msg,
                cost_or_token_usage=adapter_res.cost_or_tokens if adapter_res else {},
                artifact_references=adapter_res.artifact_refs if adapter_res else [],
                approval_reference=approval_reference,
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )

        if execution_intent is not None:
            return self.receipt_repository.finalize_execution_intent(
                execution_intent.intent_id,
                receipt,
                ambiguous=ambiguous_external_outcome,
            )
        return self.receipt_repository.save_receipt(receipt)