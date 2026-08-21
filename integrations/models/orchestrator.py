"""Bounded Multi-Agent Workflow Orchestrator.

Orchestrates sequential and conditional handoffs across the five permanent marketing agents
with strict step bounds, timeout protection, error policies, and trace logging.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from schemas.protocol import AgentRole, CollaborationTrace, HandoffType, TaskEnvelope, TaskStatus
from integrations.models.base import BaseModelAdapter
from integrations.models.cost_governance import CostGovernanceConfig, CostTracker
from integrations.models.invocation import AgentRunResult, invoke_agent

logger = logging.getLogger("workflow_orchestrator")


class WorkflowStep(BaseModel):
    """Configuration for an individual workflow execution step."""
    step_id: str = Field(default_factory=lambda: f"STEP-{uuid.uuid4().hex[:8]}")
    agent_id: str
    output_schema: str = "StandardAgentResult"
    context_keys_to_pass: List[str] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    """Declarative workflow execution blueprint."""
    workflow_id: str = Field(default_factory=lambda: f"WF-{uuid.uuid4().hex[:8]}")
    name: str
    steps: List[WorkflowStep]
    max_agent_steps: int = Field(default=10, ge=1, le=25)
    max_model_calls: int = Field(default=20, ge=1, le=50)
    timeout_seconds: float = Field(default=120.0, ge=1.0)
    stop_on_error: bool = True


class WorkflowExecutionSummary(BaseModel):
    """Audit summary of an executed multi-agent workflow."""
    workflow_id: str
    status: TaskStatus = TaskStatus.COMPLETED
    steps_executed: int = 0
    results: List[AgentRunResult] = Field(default_factory=list)
    traces: List[CollaborationTrace] = Field(default_factory=list)
    total_cost_summary: Dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    error: Optional[str] = None


class WorkflowOrchestrator:
    """Executes multi-agent workflows with strict bounded recursion and trace capture."""

    def __init__(
        self,
        adapter: BaseModelAdapter,
        cost_config: Optional[CostGovernanceConfig] = None,
    ) -> None:
        self.adapter = adapter
        self.cost_tracker = CostTracker(cost_config)

    def run_workflow(
        self,
        initial_task: TaskEnvelope,
        workflow_def: WorkflowDefinition,
    ) -> WorkflowExecutionSummary:
        """Run a bounded workflow across marketing agents."""
        start_time = time.perf_counter()
        results: List[AgentRunResult] = []
        traces: List[CollaborationTrace] = []

        current_task = initial_task
        previous_agent: Optional[AgentRole] = None
        context_accumulator: Dict[str, Any] = {}

        for step_idx, step in enumerate(workflow_def.steps):
            # 1. Step bound guardrail
            if step_idx >= workflow_def.max_agent_steps:
                return WorkflowExecutionSummary(
                    workflow_id=workflow_def.workflow_id,
                    status=TaskStatus.FAILED,
                    steps_executed=step_idx,
                    results=results,
                    traces=traces,
                    total_cost_summary=self.cost_tracker.summary(),
                    duration_seconds=time.perf_counter() - start_time,
                    error=f"STEP_LIMIT_EXCEEDED: Exceeded max allowed steps ({workflow_def.max_agent_steps}).",
                )

            # 2. Timeout guardrail
            elapsed = time.perf_counter() - start_time
            if elapsed >= workflow_def.timeout_seconds:
                return WorkflowExecutionSummary(
                    workflow_id=workflow_def.workflow_id,
                    status=TaskStatus.FAILED,
                    steps_executed=step_idx,
                    results=results,
                    traces=traces,
                    total_cost_summary=self.cost_tracker.summary(),
                    duration_seconds=elapsed,
                    error=f"WORKFLOW_TIMEOUT: Elapsed time ({elapsed:.1f}s) exceeded limit ({workflow_def.timeout_seconds}s).",
                )

            # 3. Prepare task envelope for current agent
            target_role = AgentRole(step.agent_id.upper())
            step_envelope = TaskEnvelope(
                task_id=f"{initial_task.task_id}-S{step_idx+1}",
                parent_task_id=initial_task.task_id,
                objective=current_task.objective,
                business_context=current_task.business_context,
                product_id=current_task.product_id,
                brand_id=current_task.brand_id,
                known_facts=current_task.known_facts,
                unknown_facts=current_task.unknown_facts,
                assumptions=current_task.assumptions,
                hypotheses=current_task.hypotheses,
                owner_agent=target_role,
                output_schema=step.output_schema,
                escalation_rule=current_task.escalation_rule,
                next_action=current_task.next_action,
            )

            # 4. Invoke Agent
            res = invoke_agent(
                agent_id=step.agent_id,
                task_envelope=step_envelope,
                adapter=self.adapter,
                context=context_accumulator,
                cost_tracker=self.cost_tracker,
            )
            results.append(res)

            # 5. Record Collaboration Trace if there was a previous agent
            if previous_agent:
                trace = CollaborationTrace(
                    trace_id=f"TRACE-{uuid.uuid4().hex[:8]}",
                    task_id=step_envelope.task_id,
                    from_agent=previous_agent,
                    to_agent=target_role,
                    handoff_type=HandoffType.DELEGATION,
                    input_summary=f"Handoff from {previous_agent.value} to {target_role.value}",
                    facts_preserved=step_envelope.known_facts,
                    assumptions_preserved=step_envelope.assumptions,
                    unknowns_preserved=step_envelope.unknown_facts,
                    output_reference=f"result_{step_idx}",
                    status=res.status,
                )
                traces.append(trace)

            # 6. Error handling
            if res.status != TaskStatus.COMPLETED:
                if workflow_def.stop_on_error:
                    return WorkflowExecutionSummary(
                        workflow_id=workflow_def.workflow_id,
                        status=TaskStatus.FAILED,
                        steps_executed=step_idx + 1,
                        results=results,
                        traces=traces,
                        total_cost_summary=self.cost_tracker.summary(),
                        duration_seconds=time.perf_counter() - start_time,
                        error=f"Step {step_idx + 1} ({step.agent_id}) failed: {res.error}",
                    )

            # 7. Update state for next step
            previous_agent = target_role
            context_accumulator[f"step_{step_idx+1}_{step.agent_id}"] = res.output
            current_task.unknown_facts = res.unknown_facts
            current_task.assumptions = res.assumptions
            current_task.hypotheses = res.hypotheses

        return WorkflowExecutionSummary(
            workflow_id=workflow_def.workflow_id,
            status=TaskStatus.COMPLETED,
            steps_executed=len(workflow_def.steps),
            results=results,
            traces=traces,
            total_cost_summary=self.cost_tracker.summary(),
            duration_seconds=time.perf_counter() - start_time,
        )
