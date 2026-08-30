"""Agent Invocation Contract and Execution Bridge.

Constructs prompts from Agent DNA + TaskEnvelope, executes model completion,
and validates structured AgentRunResult with qualitative semantic confidence
without exposing private chain-of-thought.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from schemas.protocol import TaskEnvelope, TaskStatus
from integrations.models.agent_loader import AgentLoader
from integrations.models.base import (
    BaseModelAdapter,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)
from integrations.models.cost_governance import CostTracker

logger = logging.getLogger("agent_invocation")


class SemanticConfidence(str, Enum):
    """Standard qualitative confidence tiers across marketing agents."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class AgentRunResult(BaseModel):
    """Normalized structured outcome of an individual agent invocation."""
    run_id: str = Field(default_factory=lambda: f"RUN-{uuid.uuid4().hex[:12]}")
    agent_id: str
    task_id: str
    product_id: str
    status: TaskStatus = TaskStatus.COMPLETED
    output: Dict[str, Any] = Field(default_factory=dict, description="Structured decision-useful output")
    confidence: str = Field(default="HIGH", description="Qualitative confidence tier: LOW | MEDIUM | HIGH")
    confidence_rationale: str = Field(default="", description="Qualitative justification for confidence rating")
    statistical_confidence: Optional[float] = Field(
        default=None,
        description="Optional computed statistical quantity when rigorous measurement exists, never uncalibrated decimals",
    )
    evidence_references: List[str] = Field(default_factory=list)
    unknown_facts: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)
    next_action: str = ""
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: float = 0.0
    error: Optional[str] = None


class OutputValidationState:
    VALID = "VALID"
    REPAIRABLE = "REPAIRABLE"
    INVALID = "INVALID"


def parse_and_validate_agent_json(raw_text: str) -> tuple[str, Optional[Dict[str, Any]]]:
    """Parse model text into a structured dictionary without inventing missing JSON.

    REPAIRABLE is reserved for extracting an already-complete JSON object from
    harmless markdown/prose wrappers. Truncated or structurally incomplete JSON
    fails closed so a model/provider cutoff can never be converted into a
    synthetic successful payload by appending guessed delimiters.
    """
    cleaned = raw_text.strip()

    # Try direct parse.
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return OutputValidationState.VALID, data
    except Exception:
        pass

    # Extract an already-complete JSON object from a markdown code fence.
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict):
                return OutputValidationState.REPAIRABLE, data
        except Exception:
            pass

    # Extract an already-complete outer JSON object surrounded by prose.
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(raw_text[start : end + 1])
            if isinstance(data, dict):
                return OutputValidationState.REPAIRABLE, data
        except Exception:
            pass

    # Never append guessed braces/brackets/quotes to truncated model output.
    return OutputValidationState.INVALID, None


def normalize_confidence_tier(raw_confidence: Any) -> tuple[str, Optional[float]]:
    """Normalize raw confidence input into qualitative tier and optional statistical float."""
    if isinstance(raw_confidence, str):
        upper_c = raw_confidence.strip().upper()
        if upper_c in {"LOW", "MEDIUM", "HIGH", "UNKNOWN"}:
            return upper_c, None
        return upper_c, None
    elif isinstance(raw_confidence, (int, float)):
        # Numeric value returned by model; map to qualitative tier while retaining raw number
        val = float(raw_confidence)
        tier = "HIGH" if val >= 0.8 else ("MEDIUM" if val >= 0.4 else "LOW")
        return tier, val
    return "UNKNOWN", None


def invoke_agent(
    agent_id: str,
    task_envelope: TaskEnvelope,
    adapter: BaseModelAdapter,
    model_name: str = "default",
    temperature: float = 1.0,
    context: Optional[Dict[str, Any]] = None,
    loader: Optional[AgentLoader] = None,
    cost_tracker: Optional[CostTracker] = None,
    max_retries: int = 2,
) -> AgentRunResult:
    """Execute a single agent invocation cycle."""
    start_total_time = time.perf_counter()
    loader = loader or AgentLoader()

    # 1. Load Agent DNA (validates agent_id is one of the 5 permanent agents)
    try:
        agent_def = loader.load_agent(agent_id)
    except Exception as e:
        latency_ms = (time.perf_counter() - start_total_time) * 1000.0
        return AgentRunResult(
            agent_id=agent_id,
            task_id=task_envelope.task_id,
            product_id=task_envelope.product_id,
            status=TaskStatus.FAILED,
            error=f"AGENT_LOAD_FAILED: {str(e)}",
            latency_ms=latency_ms,
        )

    # 2. Check cost governance / budget bounds before calling model
    if cost_tracker:
        try:
            cost_tracker.check_budget_limits()
        except RuntimeError as e:
            latency_ms = (time.perf_counter() - start_total_time) * 1000.0
            return AgentRunResult(
                agent_id=agent_def.agent_id,
                task_id=task_envelope.task_id,
                product_id=task_envelope.product_id,
                status=TaskStatus.FAILED,
                error=str(e),
                latency_ms=latency_ms,
            )

    # 3. Assemble System Prompt
    system_prompt = (
        f"You are the {agent_def.name} in a 5-agent AI Marketing Department.\n\n"
        f"--- OPERATING DNA ---\n"
        f"{agent_def.system_dna}\n\n"
        f"--- MANDATORY GOVERNANCE CONTRACT ---\n"
        f"1. You must output strictly valid JSON conforming to the requested schema.\n"
        f"2. Do NOT output private chain-of-thought tokens or conversational filler.\n"
        f"3. Strictly preserve all KNOWN_FACTS, UNKNOWN_FACTS, and ASSUMPTIONS without fabricating data.\n"
        f"4. Confidence MUST be a qualitative tier ('LOW', 'MEDIUM', 'HIGH') with explicit 'confidence_rationale'.\n"
        f"5. Maintain product isolation for PRODUCT_ID: '{task_envelope.product_id}'.\n"
    )

    # 4. Assemble User Task Payload
    task_payload = {
        "TASK_ID": task_envelope.task_id,
        "PRODUCT_ID": task_envelope.product_id,
        "BRAND_ID": task_envelope.brand_id,
        "OBJECTIVE": task_envelope.objective,
        "BUSINESS_CONTEXT": task_envelope.business_context,
        "KNOWN_FACTS": task_envelope.known_facts,
        "UNKNOWN_FACTS": task_envelope.unknown_facts,
        "ASSUMPTIONS": task_envelope.assumptions,
        "HYPOTHESES": task_envelope.hypotheses,
        "OUTPUT_SCHEMA_REQUESTED": task_envelope.output_schema,
        "EXTRA_CONTEXT": context or {},
        "REQUIRED_JSON_OUTPUT_STRUCTURE": {
            "output": {"summary": "Decision-useful summary", "details": {}},
            "confidence": "LOW | MEDIUM | HIGH",
            "confidence_rationale": "Explicit qualitative rationale for the assigned confidence tier",
            "evidence_references": [],
            "unknown_facts": ["Preserved or newly discovered knowledge gaps"],
            "assumptions": ["Preserved working assumptions"],
            "hypotheses": ["Falsifiable hypotheses"],
            "next_action": "Recommended next specialist handoff or action",
        },
    }

    messages = [
        ModelMessage(role=ModelRole.SYSTEM, content=system_prompt),
        ModelMessage(
            role=ModelRole.USER,
            content=f"Execute this task envelope and return valid JSON:\n\n{json.dumps(task_payload, indent=2)}",
        ),
    ]

    # 5. Execute with Bounded Retries for Malformed Outputs
    total_usage = ModelUsage()
    last_error: Optional[str] = None
    parsed_output: Optional[Dict[str, Any]] = None

    for attempt in range(max_retries + 1):
        req = ModelRequest(
            model_name=model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=8192,
            response_schema={"type": "object"},
        )

        response: ModelResponse = adapter.generate(req)

        # Record usage
        total_usage.prompt_tokens += response.usage.prompt_tokens
        total_usage.completion_tokens += response.usage.completion_tokens
        total_usage.total_tokens += response.usage.total_tokens

        if cost_tracker:
            cost_tracker.record_usage(model_name, response.usage)

        if response.status != ModelResponseStatus.SUCCESS:
            last_error = response.error or "MODEL_CALL_FAILED"
            break

        val_state, data = parse_and_validate_agent_json(response.content)
        if val_state in (OutputValidationState.VALID, OutputValidationState.REPAIRABLE) and data is not None:
            parsed_output = data
            break
        else:
            last_error = f"MALFORMED_JSON_OUTPUT on attempt {attempt + 1}: Raw snippet: {response.content[:200]}"
            # Append repair prompt for retry. The model must regenerate complete
            # JSON; local code never guesses or closes a truncated structure.
            messages.append(ModelMessage(role=ModelRole.ASSISTANT, content=response.content))
            messages.append(
                ModelMessage(
                    role=ModelRole.USER,
                    content="Your previous response was not valid complete JSON. Regenerate the full response and output ONLY raw JSON matching the required schema with qualitative confidence ('LOW', 'MEDIUM', 'HIGH').",
                )
            )

    latency_ms = (time.perf_counter() - start_total_time) * 1000.0

    if parsed_output is None:
        return AgentRunResult(
            agent_id=agent_def.agent_id,
            task_id=task_envelope.task_id,
            product_id=task_envelope.product_id,
            status=TaskStatus.FAILED,
            error=last_error,
            usage=total_usage,
            latency_ms=latency_ms,
        )

    # 6. Normalize Confidence Tier
    raw_conf = parsed_output.get("confidence", "HIGH")
    qual_confidence, stat_confidence = normalize_confidence_tier(raw_conf)
    conf_rationale = str(parsed_output.get("confidence_rationale", ""))

    # 7. Normalize into AgentRunResult
    return AgentRunResult(
        agent_id=agent_def.agent_id,
        task_id=task_envelope.task_id,
        product_id=task_envelope.product_id,
        status=TaskStatus.COMPLETED,
        output=parsed_output.get("output", parsed_output),
        confidence=qual_confidence,
        confidence_rationale=conf_rationale,
        statistical_confidence=stat_confidence,
        evidence_references=parsed_output.get("evidence_references", []),
        unknown_facts=parsed_output.get("unknown_facts", task_envelope.unknown_facts),
        assumptions=parsed_output.get("assumptions", task_envelope.assumptions),
        hypotheses=parsed_output.get("hypotheses", task_envelope.hypotheses),
        next_action=str(parsed_output.get("next_action", task_envelope.next_action)),
        usage=total_usage,
        latency_ms=latency_ms,
    )
