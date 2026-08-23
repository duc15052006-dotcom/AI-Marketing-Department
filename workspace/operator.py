"""Operator Workspace and Control Interface (Phase 6.1).

Provides an operator console API and CLI controller for launching runs,
inspecting stages, receipts, and health, approving gated actions, and managing campaign state.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from connectors.registry import ConnectorRegistry
from knowledge.ingestion import KnowledgeLifecycleManager
from knowledge.repository import KnowledgeRepository
from memory.learning import LearningRepository
from memory.learning_operations import LearningOperatorService
from memory.operations import MemoryOperatorService
from memory.repository import MemoryRepository
from runtime.artifacts import DepartmentRunArtifact
from runtime.context import ApprovalState, RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from tools.capabilities import RiskLevel
from tools.receipts import ExecutionReceipt, ExecutionStatus
from tools.security import HumanApprovalRecord, PolicyEngine, compute_request_fingerprint
from tools.tool_gateway import ToolGateway
from workspace.business import BusinessRegistry, BusinessWorkspace

logger = logging.getLogger("operator_workspace")


class OperatorWorkspace:
    """Operator workspace console managing runs, connectors, approvals, and multi-brand isolation."""

    def __init__(
        self,
        runtime: FiveAgentDepartmentRuntime,
        business_registry: Optional[BusinessRegistry] = None,
        connector_registry: Optional[ConnectorRegistry] = None,
    ) -> None:
        self.runtime = runtime
        self.business_registry = business_registry or BusinessRegistry()
        self.connector_registry = connector_registry or ConnectorRegistry()
        self.memory_ops = MemoryOperatorService(self.runtime.memory_repo)
        self.learning_ops = LearningOperatorService(self.runtime.learning_repo, self.runtime.memory_repo)
        self.knowledge_lifecycle = KnowledgeLifecycleManager(self.runtime.knowledge_repo)

    # 1. Create Department Run
    def create_run(
        self,
        business_id: str,
        objective: str,
        campaign_id: Optional[str] = None,
        user_id: str = "operator",
    ) -> RuntimeContext:
        """Create a new run strictly bounded by the BusinessWorkspace scope."""
        biz = self.business_registry.get_workspace(business_id)
        cid = campaign_id or f"CAMP-{business_id[:6].upper()}-01"

        ctx = self.runtime.start_run(
            objective=objective,
            business_id=business_id,
            campaign_id=cid,
            user_id=user_id,
        )
        if biz:
            ctx.constraints.extend(biz.default_constraints)
            ctx.working_state["brand_name"] = biz.brand_name
            ctx.working_state["knowledge_scope"] = biz.knowledge_scope
            ctx.working_state["memory_scope"] = biz.memory_scope
        return ctx

    # 2. Inspect Run Status
    def get_run_status(self, run_id: str) -> Dict[str, Any]:
        """Inspect the current runtime status, stage, and checkpoint count."""
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            completed = self.runtime._completed_runs.get(run_id)
            if completed:
                return {
                    "run_id": run_id,
                    "status": completed.status.value,
                    "current_stage": "COMPLETED",
                    "artifact_hash": completed.final_artifact_hash,
                }
            return {"run_id": run_id, "status": "NOT_FOUND"}

        return {
            "run_id": ctx.run_id,
            "business_id": ctx.business_id,
            "status": ctx.status.value,
            "current_stage": ctx.current_stage.value,
            "completed_stages": list(ctx.stage_outputs.keys()),
            "checkpoints_count": len(ctx.checkpoints),
            "receipts_count": len(ctx.execution_receipt_refs),
        }

    # 3. Inspect Connector Health (Zero Secret Exposure)
    def inspect_connector_health(self) -> Dict[str, Dict[str, Any]]:
        """Return diagnostic health summary of all registered connectors."""
        return self.connector_registry.list_connector_health()

    # 4. Approve Gated Action
    def approve_gated_action(
        self,
        run_id: str,
        approval_token: Optional[str] = None,
        action_type: str = "social_publishing",
        approved_by: str = "Executive Operator",
        parameters: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Register human approval record and resume a paused/waiting run."""
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            return False

        publish_params = parameters or {"platform": "linkedin", "content": "Campaign Go-To-Market Plan"}

        if approval_token:
            if approval_token not in self.runtime.tool_gateway.policy_engine._approved_tokens:
                fp = compute_request_fingerprint(
                    capability_id=action_type,
                    parameters=publish_params,
                    run_id=ctx.run_id,
                    business_id=ctx.business_id,
                )
                record = HumanApprovalRecord(
                    approval_token=approval_token,
                    action_type=action_type,
                    capability_id=action_type,
                    run_id=ctx.run_id,
                    business_id=ctx.business_id,
                    request_fingerprint=fp,
                    approved_by=approved_by,
                    approved_at=datetime.now(timezone.utc).isoformat(),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    expires_at=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 300, tz=timezone.utc).isoformat(),
                    scope=ctx.business_id,
                    risk_level=RiskLevel.CRITICAL,
                    consumed=False,
                )
                self.runtime.tool_gateway.policy_engine.register_approval(record)
            tok_to_use = approval_token
        else:
            record = self.runtime.tool_gateway.policy_engine.create_server_approval(
                capability_id=action_type,
                parameters=publish_params,
                run_id=ctx.run_id,
                business_id=ctx.business_id,
                approved_by=approved_by,
                ttl_seconds=300,
                risk_level=RiskLevel.CRITICAL,
                scope=ctx.business_id,
            )
            tok_to_use = record.approval_token

        ctx.approval_refs.append(tok_to_use)

        # Resume publishing execution
        receipt = self.runtime.request_publish_action(ctx, platform="linkedin", approval_token=tok_to_use)
        return receipt.status == ExecutionStatus.SUCCESS

    # 5. Reject Gated Action
    def reject_gated_action(self, run_id: str, reason: str = "Rejected by operator") -> bool:
        """Record human rejection of a gated action."""
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            return False
        ctx.status = RuntimeStatus.PAUSED
        ctx.working_state["rejection_reason"] = reason
        ctx.create_checkpoint()
        return True

    # 6. Pause / Resume / Cancel
    def pause_run(self, run_id: str) -> bool:
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            return False
        ctx.status = RuntimeStatus.PAUSED
        ctx.create_checkpoint()
        return True

    def resume_run(self, run_id: str) -> bool:
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            return False
        ctx.status = RuntimeStatus.RUNNING
        ctx.create_checkpoint()
        return True

    def cancel_run(self, run_id: str, reason: str = "Cancelled by operator") -> bool:
        ctx = self.runtime._active_contexts.get(run_id)
        if not ctx:
            return False
        ctx.status = RuntimeStatus.CANCELLED
        ctx.working_state["cancellation_reason"] = reason
        ctx.create_checkpoint()
        return True

    # 7. Complete Supervised Campaign Workflow
    def execute_supervised_campaign(
        self,
        business_id: str,
        objective: str,
        auto_approve_token: Optional[str] = None,
    ) -> DepartmentRunArtifact:
        """Execute full end-to-end campaign workflow under operator supervision."""
        ctx = self.create_run(business_id=business_id, objective=objective)

        # Stage 1: CMO Initial
        self.runtime.execute_stage_cmo_initial(ctx)
        # Stage 2: Intelligence
        self.runtime.execute_stage_intelligence(ctx)
        # Stage 3: Strategist
        self.runtime.execute_stage_strategist(ctx)
        # Stage 4: Creative
        self.runtime.execute_stage_creative(ctx)
        # Stage 5: Performance
        self.runtime.execute_stage_performance(ctx)
        # Stage 6: Final CMO
        self.runtime.execute_stage_final_cmo(ctx)

        # Gated publishing step
        if auto_approve_token:
            self.approve_gated_action(ctx.run_id, approval_token=auto_approve_token)
        else:
            self.runtime.request_publish_action(ctx, platform="linkedin", approval_token=None)

        return self.runtime.complete_run(ctx)
