"""Contracts for the platform plugin system.

Plugins are declarative by default: a manifest can declare tools, but it cannot
execute arbitrary import paths. Runtime executors must be bound explicitly by
trusted application code before a plugin tool can run.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List

from schemas.base import BaseModel, Field


class PluginState(str, Enum):
    DISCOVERED = "DISCOVERED"
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"


class PluginToolDeclaration(BaseModel):
    """One tool exposed by a plugin manifest."""

    name: str = Field(..., min_length=1, max_length=96)
    description: str = Field(..., min_length=1, max_length=2000)
    category: str = "OBSERVE"
    evidence_role: str = "NONE"
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    required_permissions: List[str] = Field(default_factory=lambda: ["READ_ONLY"])
    risk_level: str = "HIGH"
    human_approval_required: bool = True
    supported_agents: List[str] = Field(default_factory=lambda: ["all"])
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=300.0)


class PluginManifest(BaseModel):
    """Declarative plugin manifest stored and fingerprinted by the registry."""

    plugin_id: str = Field(..., min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=128)
    version: str = Field(..., min_length=1, max_length=48)
    api_version: str = "1"
    description: str = ""
    tools: List[PluginToolDeclaration] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class PluginRecord(BaseModel):
    """Registry snapshot for an installed/discovered plugin."""

    manifest: PluginManifest
    state: PluginState = PluginState.DISABLED
    fingerprint: str
