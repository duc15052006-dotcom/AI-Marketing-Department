"""Trusted Runtime-Owned Progress Event System (PROD-STREAMING-IMPLEMENTATION-01-B2).

Defines deterministic, typed, runtime-owned progress events:
- Strictly emitted by trusted runtime code (never model-controlled).
- Monotonically increasing per-run sequence numbers (1, 2, 3...).
- Distinct typed modes: FULL_WORKFLOW, RESEARCH_INQUIRY, GENERAL_CONVERSATION.
- Typed stage and agent enums with validation preventing rogue entities (e.g. AGENT_6).
- Isolates event sinks so consumer failures never corrupt business execution.
- Lifecycle finalization releases sink references upon terminalization.
- Prevents secret/credential leakage in event payloads and metadata.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from schemas.base import BaseModel, Field, ValidationError

logger = logging.getLogger("runtime_progress")


class ProgressEventType(str, Enum):
    """Finite, typed lifecycle progress event types."""
    RUN_STARTED = "RUN_STARTED"
    ROUTE_SELECTED = "ROUTE_SELECTED"
    RESEARCH_STARTED = "RESEARCH_STARTED"
    RESEARCH_SEARCH_STARTED = "RESEARCH_SEARCH_STARTED"
    RESEARCH_SEARCH_COMPLETED = "RESEARCH_SEARCH_COMPLETED"
    RESEARCH_EVIDENCE_READY = "RESEARCH_EVIDENCE_READY"
    STAGE_STARTED = "STAGE_STARTED"
    STAGE_COMPLETED = "STAGE_COMPLETED"
    MODEL_STARTED = "MODEL_STARTED"
    MODEL_COMPLETED = "MODEL_COMPLETED"
    RUN_COMPLETED = "RUN_COMPLETED"
    RUN_FAILED = "RUN_FAILED"


class ProgressMode(str, Enum):
    """Execution modality for progress classification."""
    FULL_WORKFLOW = "FULL_WORKFLOW"
    RESEARCH_INQUIRY = "RESEARCH_INQUIRY"
    GENERAL_CONVERSATION = "GENERAL_CONVERSATION"


class ProgressStage(str, Enum):
    """Finite canonical execution stages for progress events (exactly 6 stages)."""
    CMO_INITIAL = "CMO_INITIAL"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGIST = "STRATEGIST"
    CREATIVE = "CREATIVE"
    PERFORMANCE = "PERFORMANCE"
    FINAL_CMO = "FINAL_CMO"


class ProgressAgent(str, Enum):
    """Finite canonical agent identifiers for progress events."""
    CMO = "CMO"
    INTELLIGENCE = "INTELLIGENCE"
    STRATEGIST = "STRATEGIST"
    CREATIVE = "CREATIVE"
    PERFORMANCE = "PERFORMANCE"


def runtime_stage_to_progress_stage(stage: Any) -> Optional[ProgressStage]:
    """Map runtime stage lifecycle to canonical ProgressStage.

    Canonical mappings:
      - CMO_INITIAL -> ProgressStage.CMO_INITIAL
      - INTELLIGENCE -> ProgressStage.INTELLIGENCE
      - STRATEGIST -> ProgressStage.STRATEGIST
      - CREATIVE -> ProgressStage.CREATIVE
      - PERFORMANCE -> ProgressStage.PERFORMANCE
      - FINAL_CMO -> ProgressStage.FINAL_CMO

    Noncanonical lifecycle values (INIT, COMPLETED, FAILED, CANCELLED, etc.) -> None.
    """
    if stage is None:
        return None
    if isinstance(stage, ProgressStage):
        return stage
    val = stage.value if hasattr(stage, "value") else str(stage)
    try:
        return ProgressStage(val)
    except (ValueError, KeyError):
        return None


def _sanitize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize metadata to strictly prevent secret, credential or token exposure."""
    sanitized: Dict[str, Any] = {}
    sensitive_keys = {
        "api_key", "apikey", "secret", "token", "authorization", "auth",
        "password", "credential", "cred", "private_key", "secret_key",
    }
    for k, v in metadata.items():
        k_lower = str(k).lower()
        if any(s in k_lower for s in sensitive_keys):
            continue
        if isinstance(v, str):
            if v.startswith("Bearer ") or v.startswith("sk-") or "eyJh" in v:
                continue
        sanitized[k] = v
    return sanitized


class RuntimeProgressEvent(BaseModel):
    """Immutable, typed runtime progress event."""
    event_type: ProgressEventType
    run_id: str
    sequence: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: Optional[ProgressMode] = None
    stage: Optional[ProgressStage] = None
    agent: Optional[ProgressAgent] = None
    message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()

        # Enforce typed event_type
        if not isinstance(self.event_type, ProgressEventType):
            try:
                object.__setattr__(self, "event_type", ProgressEventType(self.event_type))
            except Exception as e:
                raise ValidationError(f"INVALID_PROGRESS_EVENT_TYPE: '{self.event_type}' is not a valid ProgressEventType.") from e

        # Enforce typed mode
        if self.mode is not None:
            if not isinstance(self.mode, ProgressMode):
                try:
                    object.__setattr__(self, "mode", ProgressMode(self.mode))
                except Exception as e:
                    raise ValidationError(f"INVALID_PROGRESS_MODE: '{self.mode}' is not a valid ProgressMode.") from e

        # Enforce typed stage
        if self.stage is not None:
            if not isinstance(self.stage, ProgressStage):
                try:
                    object.__setattr__(self, "stage", ProgressStage(self.stage))
                except Exception as e:
                    raise ValidationError(f"INVALID_PROGRESS_STAGE: '{self.stage}' is not a valid ProgressStage.") from e

        # Enforce typed agent
        if self.agent is not None:
            if not isinstance(self.agent, ProgressAgent):
                try:
                    object.__setattr__(self, "agent", ProgressAgent(self.agent))
                except Exception as e:
                    raise ValidationError(f"INVALID_PROGRESS_AGENT: '{self.agent}' is not a valid ProgressAgent.") from e

        # Enforce sanitization on metadata
        if self.metadata:
            object.__setattr__(self, "metadata", _sanitize_metadata(self.metadata))


ProgressSink = Callable[[RuntimeProgressEvent], None]


class ProgressEmitter:
    """Run-scoped sequence authority and safe progress event emitter."""

    def __init__(
        self,
        run_id: str,
        mode: Union[ProgressMode, str] = ProgressMode.FULL_WORKFLOW,
        sink: Optional[ProgressSink] = None,
    ) -> None:
        self.run_id = run_id
        self.mode = ProgressMode(mode) if isinstance(mode, str) else mode
        self.sink = sink
        self._sequence = 0
        self._events: List[RuntimeProgressEvent] = []
        self._closed = False

    @property
    def current_sequence(self) -> int:
        return self._sequence

    @property
    def events(self) -> List[RuntimeProgressEvent]:
        return list(self._events)

    @property
    def is_closed(self) -> bool:
        return self._closed

    def finalize(self) -> None:
        """Terminalize emitter, releasing sink callback reference."""
        self._closed = True
        self.sink = None

    def emit(
        self,
        event_type: Union[ProgressEventType, str],
        stage: Optional[Union[ProgressStage, str]] = None,
        agent: Optional[Union[ProgressAgent, str]] = None,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        mode: Optional[Union[ProgressMode, str]] = None,
    ) -> Optional[RuntimeProgressEvent]:
        """Emit a typed progress event with strictly monotonic sequence numbers.

        Late emit guard: if emitter has been finalized, do not advance sequence,
        do not append to event history, and do not invoke sink.
        """
        if self._closed:
            logger.warning(
                f"Attempted to emit progress event on finalized emitter for run {self.run_id} (ignored)."
            )
            return None

        self._sequence += 1
        meta = dict(metadata) if metadata else {}
        event_mode = mode or self.mode

        event = RuntimeProgressEvent(
            event_type=event_type if isinstance(event_type, ProgressEventType) else ProgressEventType(event_type),
            run_id=self.run_id,
            sequence=self._sequence,
            mode=event_mode if isinstance(event_mode, ProgressMode) else ProgressMode(event_mode),
            stage=stage if (stage is None or isinstance(stage, ProgressStage)) else ProgressStage(stage),
            agent=agent if (agent is None or isinstance(agent, ProgressAgent)) else ProgressAgent(agent),
            message=message,
            metadata=meta,
        )
        self._events.append(event)

        if self.sink is not None:
            try:
                self.sink(event)
            except Exception as exc:
                # Event sink failure policy: isolated & logged, never crashes business run
                logger.warning(
                    f"Progress sink error on event {event.event_type.value} for run {self.run_id}: {exc}"
                )

        return event
