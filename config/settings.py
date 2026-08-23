"""System Configuration and Security Settings (PROD-CONFIG-01).

Central configuration defining system environments, autonomy modes,
and workspace isolation directories without hardcoded secrets.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, List
from schemas.base import BaseModel, Field


class AutonomyMode(str, Enum):
    """System Autonomy Modes."""
    MANUAL = "MANUAL"
    SUPERVISED = "SUPERVISED"  # Default mode
    AUTONOMOUS = "AUTONOMOUS"


def _get_runtime():
    from config.authority import get_runtime_config
    return get_runtime_config()


class Settings(BaseModel):
    """Core settings model loaded from central ConfigurationAuthority."""
    app_name: str = "AI Marketing Department"
    version: str = "1.0.0-foundational"
    environment: str = Field(default_factory=lambda: _get_runtime().environment)
    autonomy_mode: AutonomyMode = Field(
        default_factory=lambda: AutonomyMode(_get_runtime().autonomy_mode)
    )

    # Base workspace directories
    base_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    products_dir: Path = Field(default_factory=lambda: Path("products"))
    knowledge_dir: Path = Field(default_factory=lambda: Path("knowledge"))
    memory_dir: Path = Field(default_factory=lambda: Path("memory"))
    logs_dir: Path = Field(default_factory=lambda: Path("logs"))

    # Security & Guardrail thresholds (validated by ConfigurationAuthority)
    max_auto_budget_usd: float = Field(
        default_factory=lambda: _get_runtime().max_auto_budget_usd
    )
    max_daily_budget_change_pct: float = Field(
        default_factory=lambda: _get_runtime().max_daily_budget_change_pct
    )
    require_evidence_citations: bool = True
    audit_logging_enabled: bool = True

    # Active model provider keys are kept strictly in backend environment
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    gemini_api_key: str = Field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))


settings = Settings()
