"""Logical Model Profiles and Task-Specific Routing (Phase 4.3C).

Decouples agent reasoning from specific model names:
Agents request a functional profile (e.g. MARKETING_REASONING, CREATIVE, RESEARCH)
instead of hardcoding provider/model strings.

Configuration-driven mappings allow switching models/providers globally without touching agent code.
"""

from __future__ import annotations

from enum import Enum
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("model_profiles")


class ModelProfile(str, Enum):
    """Standard logical model profiles used by agents."""
    MARKETING_REASONING = "MARKETING_REASONING"
    RESEARCH = "RESEARCH"
    CREATIVE = "CREATIVE"
    ANALYTICS = "ANALYTICS"
    CHEAP_JSON = "CHEAP_JSON"
    VISION = "VISION"
    CODING = "CODING"


class ProfileManager:
    """Manages profile-to-model priority chains."""

    def __init__(self) -> None:
        self._profile_map: Dict[str, List[Tuple[str, str]]] = {}
        self._load_default_profiles()

    def _load_default_profiles(self) -> None:
        """Register default priority chains (provider_id, model_id)."""
        self._profile_map = {
            ModelProfile.MARKETING_REASONING.value: [
                ("xkiro", "mistralai/mistral-large-2512"),
                ("gemini", "gemini-flash-latest"),
            ],
            ModelProfile.RESEARCH.value: [
                ("xkiro", "mistralai/mistral-large-2512"),
                ("gemini", "gemini-flash-latest"),
            ],
            ModelProfile.CREATIVE.value: [
                ("xkiro", "mistralai/mistral-large-2512"),
                ("gemini", "gemini-flash-latest"),
            ],
            ModelProfile.ANALYTICS.value: [
                ("gemini", "gemini-flash-latest"),
                ("xkiro", "mistralai/mistral-large-2512"),
            ],
            ModelProfile.CHEAP_JSON.value: [
                ("gemini", "gemini-flash-latest"),
                ("xkiro", "mistralai/mistral-large-2512"),
            ],
            ModelProfile.VISION.value: [
                ("gemini", "gemini-flash-latest"),
            ],
            ModelProfile.CODING.value: [
                ("xkiro", "mistralai/mistral-large-2512"),
                ("gemini", "gemini-flash-latest"),
            ],
        }

    def register_profile(self, profile_name: str, model_chain: List[Tuple[str, str]]) -> None:
        """Register or override a profile priority chain."""
        self._profile_map[profile_name.upper()] = model_chain
        logger.info(f"Updated model profile: {profile_name.upper()} -> {model_chain}")

    def get_models_for_profile(self, profile_name: str) -> List[Tuple[str, str]]:
        """Retrieve ordered (provider_id, model_id) tuples for given profile."""
        key = profile_name.upper()
        return self._profile_map.get(key, [("gemini", "gemini-flash-latest")])
