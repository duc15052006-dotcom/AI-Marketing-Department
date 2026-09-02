"""Universal Tool Gateway (Phase 5.1).

The single unified access point for all external and operational capabilities
across the Five-Agent Department:
- Decouples Five-Agent Brain from external tools and platforms
- Strict RBAC permission enforcement
- Human Approval Gate for high-risk / publishing / financial actions
- Side-effect-safe retry, timeout handling, and error normalization
- Generates immutable ExecutionReceipts for every invocation
- Journals consequential execution intent before adapter dispatch
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
from tools.capabilities import (
    CapabilityCategory,
    CapabilityDescriptor,
    CapabilityRegistry,
    PermissionLevel,
    RiskLevel,
)
from tools.idempotency import (
    IdempotencyConflictError,
    IdempotencyLedger,
    IdempotencyStoreError,
)
from tools.receipts import (
    ExecutionIntentState,
    ExecutionMode,
    ExecutionReceipt,
    ExecutionReceiptRepository,
    ExecutionStatus,
)
from tools.security import PolicyEngine

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
    brand_id: Optional[str] = Field(default=None, description="Trusted brand scope for account-bound operations")
    chat_id: Optional[str] = Field(default=None, description="Associated chat session ID")

    def calculate_request_hash(
        self,
        *,
        business_id: Optional[str] = None,
        project_id: Optional[str] = None,
        brand_id: Optional[str] = None,
    ) -> str:
        """Compute SHA-256 hash of parameters plus trusted execution scope."""
        effective_business_id = self.business_id if business_id is None else business_id
        effective_project_id = self.project_id if project_id is None else project_id
        effective_brand_id = self.brand_id if brand_id is None else brand_id
        payload = json.dumps(self.parameters, sort_keys=True, ensure_ascii=False)
        if effective_business_id is None and effective_project_id is None and effective_brand_id is None:
            raw = f"{self.run_id}:{self.agent_id}:{self.capability_id}:{payload}"
        else:
            raw = (
                f"v2:{self.run_id}:{self.agent_id}:{self.capability_id}:"
                f"{effective_business_id or ''}:{effective_project_id or ''}:{effective_brand_id or ''}:{payload}"
            )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ToolGateway:
    """Central gateway orchestrating capability executions with policy and receipts."""

    def __init__(
        self,
        capability_registry: Optional[CapabilityRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        receipt_repository: Optional[ExecutionReceiptRepository] = None,
    ) -> None:
        if capability_registry is None:
            raise ValueError(
                "ToolGateway requires an explicit CapabilityRegistry instance. "
                "Pass capability_registry= to the constructor."
            )
        self.registry = capability_registry
        self.policy_engine = policy_engine or PolicyEngine()
        self.receipt_repository = receipt_repository or ExecutionReceiptRepository()
        self.idempotency_ledger = IdempotencyLedger(
            database_path=self.receipt_repository.database_path
        )
        self._adapters: Dict[str, BaseCapabilityAdapter] = {}
        self._register_default_adapters()

    def register_adapter(
        self,
        adapter: BaseCapabilityAdapter,
        aliases: Optional[List[str]] = None,
    ) -> None:
        """Register a provider adapter and optional capability provider aliases."""
        self._adapters[adapter.adapter_name.lower()] = adapter
        if aliases:
            for alias in aliases:
                self._adapters[alias.lower()] = adapter
        logger.info(
            "Registered tool adapter: %s (aliases: %s)",
            adapter.adapter_name,
            aliases or [],
        )

    def bind_adapter_alias(self, alias: str, adapter: BaseCapabilityAdapter) -> None:
        """Explicitly bind a capability provider alias to an adapter instance."""
        self._adapters[alias.lower()] = adapter
        logger.info("Bound tool adapter alias '%s' to adapter: %s", alias, adapter.adapter_name)

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
        """Return whether dispatch can produce externally consequential side effects."""
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
        """Map only clearly transient built-in exception classes to retry codes."""
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
        """Resolve truthful execution provenance for success and failure receipts."""
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

    @staticmethod
    def _safe_approval_reference(value: Optional[str]) -> Optional[str]:
        """Return an audit reference that cannot be replayed as approval authority."""
        if not value:
            return None
        if value.startswith("pending_appr_") or value.startswith("approval_ref_"):
            return value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
        return f"approval_ref_{digest}"

    def _error_receipt(
        self,
        request: ToolRequest,
        *,
        provider: str,
        request_hash: str,
        started_at: datetime,
        status: ExecutionStatus,
        error_class: str,
        error_message: str,
        business_id: Optional[str],
        project_id: Optional[str],
        approval_reference: Optional[str] = None,
        execution_mode: ExecutionMode = ExecutionMode.MOCK,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            run_id=request.run_id,
            agent_id=request.agent_id,
            capability_id=request.capability_id,
            provider=provider,
            request_hash=request_hash,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            status=status,
            execution_mode=execution_mode,
            error_class=error_class,
            error_message=error_message,
            approval_reference=approval_reference,
            business_id=business_id,
            project_id=project_id,
            chat_id=request.chat_id,
        )

    def execute(self, request: ToolRequest) -> ExecutionReceipt:
        """Execute a tool capability with governance, durable intent, and receipts."""
        start_time = datetime.now(timezone.utc)

        # Approval authority may restore omitted trusted scope, but model-controlled
        # parameters are never used to infer business/project/brand context.
        effective_business_id = request.business_id
        effective_project_id = request.project_id
        effective_brand_id = request.brand_id
        if request.approval_token:
            approval_record = self.policy_engine.get_approval(request.approval_token)
            if approval_record is not None:
                if not effective_business_id and approval_record.business_id:
                    effective_business_id = approval_record.business_id
                if not effective_project_id and approval_record.project_id:
                    effective_project_id = approval_record.project_id
                if not effective_brand_id and approval_record.brand_id:
                    effective_brand_id = approval_record.brand_id

        req_hash = request.calculate_request_hash(
            business_id=effective_business_id,
            project_id=effective_project_id,
            brand_id=effective_brand_id,
        )

        # 1. Capability Discovery
        cap = self.registry.get_capability(request.capability_id)
        if not cap:
            return self.receipt_repository.save_receipt(
                self._error_receipt(
                    request,
                    provider="gateway",
                    request_hash=req_hash,
                    started_at=start_time,
                    status=ExecutionStatus.ERROR,
                    error_class="CAPABILITY_NOT_FOUND",
                    error_message=(
                        f"Capability '{request.capability_id}' is not registered "
                        "in CapabilityRegistry."
                    ),
                    business_id=effective_business_id,
                    project_id=effective_project_id,
                )
            )

        # 2. Permission & Safety Policy Gate
        decision = self.policy_engine.evaluate(
            agent_id=request.agent_id,
            capability=cap,
            approval_token=request.approval_token,
            run_id=request.run_id,
            business_id=effective_business_id,
            parameters=request.parameters,
            project_id=effective_project_id,
            brand_id=effective_brand_id,
        )
        if not decision.allowed:
            status = (
                ExecutionStatus.APPROVAL_REQUIRED
                if decision.requires_human_approval
                else ExecutionStatus.BLOCKED
            )
            err_class = decision.error_code or (
                "HUMAN_APPROVAL_REQUIRED"
                if decision.requires_human_approval
                else "PERMISSION_DENIED"
            )
            appr_ref = self._safe_approval_reference(request.approval_token)
            if decision.requires_human_approval and not request.approval_token:
                pending_rec = self.policy_engine.create_pending_approval(
                    capability_id=request.capability_id,
                    parameters=request.parameters,
                    run_id=request.run_id,
                    business_id=effective_business_id,
                    scope="",
                    risk_level=cap.risk_level,
                    project_id=effective_project_id,
                    brand_id=effective_brand_id,
                )
                appr_ref = pending_rec.pending_approval_id

            return self.receipt_repository.save_receipt(
                self._error_receipt(
                    request,
                    provider=cap.provider,
                    request_hash=req_hash,
                    started_at=start_time,
                    status=status,
                    error_class=err_class,
                    error_message=decision.reason,
                    approval_reference=appr_ref,
                    business_id=effective_business_id,
                    project_id=effective_project_id,
                )
            )

        # 3. Retrieve Provider Adapter
        adapter = self.get_adapter(cap.provider)
        if adapter is None:
            return self.receipt_repository.save_receipt(
                self._error_receipt(
                    request,
                    provider=cap.provider,
                    request_hash=req_hash,
                    started_at=start_time,
                    status=ExecutionStatus.ERROR,
                    error_class="PROVIDER_NOT_CONFIGURED",
                    error_message=(
                        f"Provider adapter '{cap.provider}' is not registered "
                        "with ToolGateway."
                    ),
                    business_id=effective_business_id,
                    project_id=effective_project_id,
                )
            )

        # 4. Atomic One-Shot Approval Claim for Consequential Actions
        cap_is_consequential = self._is_consequential_capability(cap)
        pinned_execution_mode = (
            self._resolve_execution_mode(adapter, cap.capability_id)
            if cap_is_consequential
            else None
        )
        is_consequential = bool(request.approval_token and cap_is_consequential)

        if is_consequential:
            claimed = self.policy_engine.claim_approval(request.approval_token)
            if not claimed:
                return self.receipt_repository.save_receipt(
                    self._error_receipt(
                        request,
                        provider=adapter.adapter_name,
                        request_hash=req_hash,
                        started_at=start_time,
                        status=ExecutionStatus.APPROVAL_REQUIRED,
                        error_class="APPROVAL_ALREADY_CLAIMED",
                        error_message=(
                            "APPROVAL_ALREADY_CLAIMED: Approval authority is unavailable, "
                            "expired, or has already been spent."
                        ),
                        approval_reference=self._safe_approval_reference(
                            request.approval_token
                        ),
                        business_id=effective_business_id,
                        project_id=effective_project_id,
                    )
                )

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
        idempotency_record = None

        try:
            # Durable idempotency authority is only engaged for REAL consequential
            # actions carrying an explicit key. Run/agent/request ids are excluded
            # from its namespace so a newly-approved replay still collides.
            raw_idempotency_key = request.parameters.get("idempotency_key")
            if (
                cap_is_consequential
                and pinned_execution_mode == ExecutionMode.REAL
                and isinstance(raw_idempotency_key, str)
                and raw_idempotency_key.strip()
            ):
                try:
                    resolved_provider = str(adapter.adapter_name or "").strip()
                    resolved_provider_key = resolved_provider.lower()

                    # Pre-fix versions persisted the capability alias as provider
                    # authority. Probe aliases still bound to this exact adapter so
                    # durable historical reservations remain fail-closed after the
                    # canonical authority switches to adapter.adapter_name.
                    for legacy_provider in sorted(
                        name
                        for name, bound_adapter in self._adapters.items()
                        if bound_adapter is adapter and name != resolved_provider_key
                    ):
                        legacy_reservation_id, _, _ = self.idempotency_ledger.reservation_identity(
                            capability_id=request.capability_id,
                            provider=legacy_provider,
                            idempotency_key=raw_idempotency_key,
                            connection_id=request.parameters.get("connection_id"),
                            business_id=effective_business_id,
                            project_id=effective_project_id,
                            brand_id=effective_brand_id,
                        )
                        legacy_record = self.idempotency_ledger.get(legacy_reservation_id)
                        if legacy_record is None:
                            continue
                        legacy_fingerprint = self.idempotency_ledger.semantic_fingerprint(
                            capability_id=request.capability_id,
                            provider=legacy_provider,
                            parameters=request.parameters,
                            business_id=effective_business_id,
                            project_id=effective_project_id,
                            brand_id=effective_brand_id,
                        )
                        if legacy_record.request_fingerprint == legacy_fingerprint:
                            conflict_code = "IDEMPOTENCY_REPLAY_BLOCKED"
                            conflict_message = (
                                "This idempotency key is already reserved for the same governed "
                                "action under a legacy provider alias; automatic replay is forbidden."
                            )
                        else:
                            conflict_code = "IDEMPOTENCY_KEY_CONFLICT"
                            conflict_message = (
                                "This idempotency key is already reserved for a different governed "
                                "action under a legacy provider alias."
                            )
                        return self.receipt_repository.save_receipt(
                            self._error_receipt(
                                request,
                                provider=adapter.adapter_name,
                                request_hash=req_hash,
                                started_at=start_time,
                                status=ExecutionStatus.BLOCKED,
                                error_class=conflict_code,
                                error_message=f"{conflict_code}: {conflict_message}",
                                approval_reference=self._safe_approval_reference(
                                    request.approval_token
                                ),
                                business_id=effective_business_id,
                                project_id=effective_project_id,
                                execution_mode=ExecutionMode.REAL,
                            )
                        )

                    idempotency_record = self.idempotency_ledger.reserve(
                        capability_id=request.capability_id,
                        provider=resolved_provider,
                        idempotency_key=raw_idempotency_key,
                        connection_id=request.parameters.get("connection_id"),
                        parameters=request.parameters,
                        business_id=effective_business_id,
                        project_id=effective_project_id,
                        brand_id=effective_brand_id,
                    )
                except IdempotencyConflictError as exc:
                    return self.receipt_repository.save_receipt(
                        self._error_receipt(
                            request,
                            provider=adapter.adapter_name,
                            request_hash=req_hash,
                            started_at=start_time,
                            status=ExecutionStatus.BLOCKED,
                            error_class=exc.code,
                            error_message=str(exc),
                            approval_reference=self._safe_approval_reference(
                                request.approval_token
                            ),
                            business_id=effective_business_id,
                            project_id=effective_project_id,
                            execution_mode=ExecutionMode.REAL,
                        )
                    )
                except IdempotencyStoreError as exc:
                    return self.receipt_repository.save_receipt(
                        self._error_receipt(
                            request,
                            provider=adapter.adapter_name,
                            request_hash=req_hash,
                            started_at=start_time,
                            status=ExecutionStatus.ERROR,
                            error_class="IDEMPOTENCY_STORE_UNAVAILABLE",
                            error_message=str(exc),
                            approval_reference=self._safe_approval_reference(
                                request.approval_token
                            ),
                            business_id=effective_business_id,
                            project_id=effective_project_id,
                            execution_mode=ExecutionMode.REAL,
                        )
                    )

            # Critical ordering invariant:
            # PREPARED -> DISPATCHING is durably committed before adapter execution.
            # Any crash after DISPATCHING and before finalization is ambiguous and
            # must never be interpreted as proof that the side effect did not run.
            if cap_is_consequential:
                try:
                    execution_intent = self.receipt_repository.prepare_execution_intent(
                        request_id=request.request_id,
                        run_id=request.run_id,
                        agent_id=request.agent_id,
                        capability_id=request.capability_id,
                        provider=adapter.adapter_name,
                        request_hash=req_hash,
                        execution_mode=pinned_execution_mode or ExecutionMode.MOCK,
                        business_id=effective_business_id,
                        project_id=effective_project_id,
                        chat_id=request.chat_id,
                        approval_reference=self._safe_approval_reference(
                            request.approval_token
                        ),
                    )
                except Exception:
                    if idempotency_record is not None:
                        try:
                            self.idempotency_ledger.release_reserved(
                                idempotency_record.reservation_id
                            )
                        except IdempotencyStoreError as cleanup_exc:
                            # Cleanup failure remains fail-closed: the reservation
                            # stays present and therefore cannot permit a replay.
                            logger.error(
                                "Failed to release undispatched idempotency reservation %s: %s",
                                idempotency_record.reservation_id,
                                cleanup_exc,
                            )
                    raise

                try:
                    self.receipt_repository.mark_execution_intent_dispatching(
                        execution_intent.intent_id
                    )
                except Exception:
                    # A transition call can fail either before or after its durable
                    # state update. Release only when the repository can prove that
                    # dispatch never started; uncertainty remains fail-closed.
                    if idempotency_record is not None:
                        try:
                            current_intent = self.receipt_repository.get_execution_intent(
                                execution_intent.intent_id
                            )
                        except Exception as inspect_exc:
                            logger.error(
                                "Failed to verify execution intent after dispatch transition error %s: %s",
                                execution_intent.intent_id,
                                inspect_exc,
                            )
                        else:
                            if (
                                current_intent is not None
                                and current_intent.state == ExecutionIntentState.PREPARED
                                and current_intent.dispatch_count == 0
                            ):
                                try:
                                    self.idempotency_ledger.release_reserved(
                                        idempotency_record.reservation_id
                                    )
                                except IdempotencyStoreError as cleanup_exc:
                                    logger.error(
                                        "Failed to release proven pre-dispatch idempotency reservation %s: %s",
                                        idempotency_record.reservation_id,
                                        cleanup_exc,
                                    )
                    raise

                if idempotency_record is not None:
                    try:
                        idempotency_record = self.idempotency_ledger.mark_dispatching(
                            idempotency_record.reservation_id
                        )
                    except IdempotencyStoreError as exc:
                        predispatch_receipt = self._error_receipt(
                            request,
                            provider=adapter.adapter_name,
                            request_hash=req_hash,
                            started_at=start_time,
                            status=ExecutionStatus.ERROR,
                            error_class="IDEMPOTENCY_STORE_UNAVAILABLE",
                            error_message=str(exc),
                            approval_reference=self._safe_approval_reference(
                                request.approval_token
                            ),
                            business_id=effective_business_id,
                            project_id=effective_project_id,
                            execution_mode=pinned_execution_mode or ExecutionMode.MOCK,
                        )
                        return self.receipt_repository.finalize_execution_intent(
                            execution_intent.intent_id,
                            predispatch_receipt,
                            ambiguous=False,
                        )

            for attempt in range(max_retries + 1):
                try:
                    scoped_execute = getattr(adapter, "execute_with_trusted_scope", None)
                    if callable(scoped_execute):
                        adapter_res = scoped_execute(
                            capability_id=cap.capability_id,
                            parameters=request.parameters,
                            timeout_seconds=timeout,
                            run_id=request.run_id,
                            business_id=effective_business_id or "",
                            project_id=effective_project_id or "",
                            brand_id=effective_brand_id or "",
                        )
                    else:
                        adapter_res = adapter.execute(
                            capability_id=cap.capability_id,
                            parameters=request.parameters,
                            timeout_seconds=timeout,
                            run_id=request.run_id,
                            business_id=effective_business_id or "",
                            project_id=effective_project_id or "",
                        )
                    last_exc = None
                    exception_error_code = None
                except Exception as exc:
                    adapter_res = None
                    last_exc = exc
                    exception_error_code = self._classify_retryable_exception(exc)

                    if cap_is_consequential:
                        ambiguous_external_outcome = True
                        break

                    if exception_error_code not in retryable_errors:
                        break
                    if attempt >= max_retries:
                        break
                    if backoff_seconds > 0:
                        time.sleep(backoff_seconds)
                    continue

                if adapter_res.success:
                    break

                if cap_is_consequential:
                    break

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
        safe_approval_ref = self._safe_approval_reference(request.approval_token)
        if adapter_res and adapter_res.success:
            mode = (
                pinned_execution_mode
                if pinned_execution_mode is not None
                else self._resolve_execution_mode(adapter, cap.capability_id, adapter_res)
            )
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
                approval_reference=safe_approval_ref,
                business_id=effective_business_id,
                project_id=effective_project_id,
                chat_id=request.chat_id,
                observation_record=adapter_res.observation_record,
            )
        else:
            if ambiguous_external_outcome:
                err_code = "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME"
                err_msg = (
                    "AMBIGUOUS_EXTERNAL_ACTION_OUTCOME: The external action may have "
                    "been accepted before execution raised an exception; automatic "
                    "retry was suppressed to prevent duplicate side effects."
                )
            elif adapter_res is not None:
                err_code = adapter_res.error_code or "EXECUTION_ERROR"
                err_msg = adapter_res.error_message or "Tool adapter execution failed."
            else:
                err_code = exception_error_code or "EXECUTION_EXCEPTION"
                err_msg = (
                    str(last_exc)
                    if last_exc is not None
                    else "Tool adapter execution failed."
                )

            status = (
                ExecutionStatus.TIMEOUT
                if err_code == "TIMEOUT"
                else ExecutionStatus.ERROR
            )
            mode = (
                pinned_execution_mode
                if pinned_execution_mode is not None
                else self._resolve_execution_mode(adapter, cap.capability_id, adapter_res)
            )
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
                approval_reference=safe_approval_ref,
                business_id=effective_business_id,
                project_id=effective_project_id,
                chat_id=request.chat_id,
            )

        if execution_intent is not None:
            stored_receipt = self.receipt_repository.finalize_execution_intent(
                execution_intent.intent_id,
                receipt,
                ambiguous=ambiguous_external_outcome,
            )
        else:
            stored_receipt = self.receipt_repository.save_receipt(receipt)

        if idempotency_record is not None:
            try:
                self.idempotency_ledger.settle(
                    idempotency_record.reservation_id,
                    ambiguous=ambiguous_external_outcome,
                )
            except IdempotencyStoreError as exc:
                # Do not transform a completed external action into a retryable
                # client failure. A DISPATCHING reservation remains fail-closed
                # and therefore still prevents duplicate replay.
                logger.error(
                    "Failed to settle idempotency reservation %s: %s",
                    idempotency_record.reservation_id,
                    exc,
                )

        return stored_receipt