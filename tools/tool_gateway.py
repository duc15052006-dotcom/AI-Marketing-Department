"""Universal Tool Gateway (Phase 5.1).

The single unified access point for all external and operational capabilities
across the Five-Agent Department:
- Decouples Five-Agent Brain from external tools and platforms
- Strict RBAC permission enforcement
- Human Approval Gate for high-risk / publishing / financial actions
- Automatic retry, timeout handling, and error normalization
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
from tools.receipts import ExecutionMode, ExecutionReceipt, ExecutionReceiptRepository, ExecutionStatus
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

        # 4. Atomic One-Shot Approval Claim for Consequential Actions
        is_consequential = bool(
            request.approval_token
            and (
                cap.human_approval_required
                or cap.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
                or cap.category == CapabilityCategory.PUBLISH
                or PermissionLevel.FINANCIAL_OR_HIGH_RISK in cap.required_permissions
                or PermissionLevel.PUBLISH in cap.required_permissions
                or PermissionLevel.EXTERNAL_WRITE in cap.required_permissions
            )
        )

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
                    approval_reference=request.approval_token,
                    business_id=request.business_id,
                    project_id=request.project_id,
                    chat_id=request.chat_id,
                )
                return self.receipt_repository.save_receipt(receipt)

        # 5. Execute Invocation with Timeout & Retries
        timeout = request.timeout_seconds or cap.timeout_policy
        max_retries = cap.retry_policy.get("max_retries", 0)
        retryable_errors = set(cap.retry_policy.get("retryable_errors", []))

        adapter_res = None
        last_exc = None
        try:
            for attempt in range(max_retries + 1):
                try:
                    adapter_res = adapter.execute(
                        capability_id=cap.capability_id,
                        parameters=request.parameters,
                        timeout_seconds=timeout,
                    )
                except Exception as e:
                    adapter_res = None
                    last_exc = e

                if adapter_res and adapter_res.success:
                    break
                if adapter_res and adapter_res.error_code not in retryable_errors:
                    break
        finally:
            if is_consequential:
                self.policy_engine.consume_approval(request.approval_token)

        completed_time = datetime.now(timezone.utc)

        # 6. Assemble Receipt
        if adapter_res and adapter_res.success:

            mode = getattr(adapter_res, "execution_mode", ExecutionMode.MOCK) or ExecutionMode.MOCK
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
                approval_reference=request.approval_token,
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )
        else:
            err_code = adapter_res.error_code if adapter_res else "EXECUTION_EXCEPTION"
            err_msg = adapter_res.error_message if adapter_res else str(last_exc)
            status = ExecutionStatus.TIMEOUT if err_code == "TIMEOUT" else ExecutionStatus.ERROR
            receipt = ExecutionReceipt(
                run_id=request.run_id,
                agent_id=request.agent_id,
                capability_id=request.capability_id,
                provider=adapter.adapter_name,
                request_hash=req_hash,
                started_at=start_time,
                completed_at=completed_time,
                status=status,
                execution_mode=ExecutionMode.MOCK,
                error_class=err_code,
                error_message=err_msg,
                cost_or_token_usage=adapter_res.cost_or_tokens if adapter_res else {},
                artifact_references=adapter_res.artifact_refs if adapter_res else [],
                approval_reference=request.approval_token,
                business_id=request.business_id,
                project_id=request.project_id,
                chat_id=request.chat_id,
            )

        return self.receipt_repository.save_receipt(receipt)
