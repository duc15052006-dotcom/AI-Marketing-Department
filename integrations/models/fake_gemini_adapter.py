"""Deterministic Fake Gemini Provider Adapter for Offline Simulation.

Conforms 100% to the production BaseModelAdapter & GeminiProviderAdapter contract:
- Synchronous generate(request: ModelRequest) -> ModelResponse
- Real ModelRequest, ModelResponse, ModelUsage, and ModelResponseStatus types
- 0 network calls / 0 live model calls
- Recorded requests history for model-parity auditing
- Sequential deterministic response queue or custom stage mapping
- Error simulation support (RATE_LIMITED / 429, ERROR / 503)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

from integrations.models.base import (
    BaseModelAdapter,
    CostPolicy,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelResponseStatus,
    ModelRole,
    ModelUsage,
)

logger = logging.getLogger("fake_gemini_adapter")


class FakeGeminiProviderAdapter(BaseModelAdapter):
    """Deterministic, zero-network fake adapter matching production GeminiProviderAdapter signature."""

    def __init__(
        self,
        default_model: str = "gemini-flash-latest",
        responses: Optional[List[Union[ModelResponse, str, Dict[str, Any]]]] = None,
        stage_response_map: Optional[Dict[str, Union[ModelResponse, str, Dict[str, Any]]]] = None,
    ) -> None:
        self._default_model = default_model
        self._responses: List[Union[ModelResponse, str, Dict[str, Any]]] = responses or []
        self._stage_response_map: Dict[str, Union[ModelResponse, str, Dict[str, Any]]] = stage_response_map or {}
        self._call_count: int = 0
        self.recorded_requests: List[ModelRequest] = []
        self.network_call_attempts: int = 0

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def cost_policy(self) -> CostPolicy:
        return CostPolicy.FREE_TIER_ALLOWED

    @property
    def automatic_fallback_allowed(self) -> bool:
        return True

    def queue_response(self, response: Union[ModelResponse, str, Dict[str, Any]]) -> None:
        """Queue another deterministic response."""
        self._responses.append(response)

    def set_stage_response(self, stage_keyword: str, response: Union[ModelResponse, str, Dict[str, Any]]) -> None:
        """Set a specific response keyed by prompt keyword (e.g. 'intelligence', 'creative')."""
        self._stage_response_map[stage_keyword.lower()] = response

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Process ModelRequest deterministically without network access."""
        self._call_count += 1
        self.recorded_requests.append(request.model_copy(deep=True))

        # Check prompt for stage mapping
        prompt_text = " ".join([m.content for m in request.messages]).lower()

        matched_resp = None
        for kw, resp_item in self._stage_response_map.items():
            if kw in prompt_text:
                matched_resp = resp_item
                break

        if matched_resp is None and self._responses:
            matched_resp = self._responses.pop(0)

        # If explicit ModelResponse is provided, return it
        if isinstance(matched_resp, ModelResponse):
            return matched_resp

        # Default fallback content if none queued
        content_str = "{}"
        if isinstance(matched_resp, dict):
            content_str = json.dumps(matched_resp)
        elif isinstance(matched_resp, str):
            content_str = matched_resp
        else:
            content_str = json.dumps({
                "executive_summary": "Simulated GTM Proposal for AI English App",
                "known_facts": ["AI conversation role-play", "15-minute daily practice mode"],
                "unknowns": ["price: TO_BE_ESTABLISHED", "budget: TO_BE_ESTABLISHED"],
                "customer_segments": ["University students", "Early-career workers"],
                "top_priority_segment": "Early-career office workers seeking interview readiness",
                "positioning": "Private, low-anxiety speaking rehearsal before high-stakes workplace meetings",
                "value_proposition": "Rehearse realistic English conversations in 15 minutes daily without judgment",
                "channel_priorities": ["Digital performance ads", "LinkedIn workplace professional content"],
                "deferred_channels": ["Offline billboard", "Expensive influencer sponsorships"],
                "what_not_to_do": ["Do not promise guaranteed IELTS band scores or native fluency"],
                "creative_territories": ["Overcoming meeting freeze", "Safe private rehearsal"],
                "selected_creative_territory": "Safe private rehearsal",
                "angles": ["Speaking anxiety reversal", "Daily 15-min workplace practice"],
                "hooks": ["Freezing before English presentations?", "Practice English meetings privately"],
                "short_form_copy": "Rehearse everyday work conversations with an AI speaking partner.",
                "video_script": "Hook: Nervous before meetings? Rehearse roleplay privately.",
                "measurement_framework": "Incremental sign-ups and active speaking session completion",
                "experiments": "Test headline messaging: workplace anxiety vs daily routine",
                "attribution_approach": "Platform tracking with holdout testing",
                "risks": ["User drop-off after trial if scenarios lack diversity"],
                "top_3_priorities": ["Scenario realism", "Onboarding friction reduction", "Privacy reassurance"],
                "go_test_hold_defer_decisions": "GO: Digital launch with private rehearsal messaging",
                "human_approval_requirements": "Authorize subscription pricing and pilot ad spend",
                "next_actions": "Review creative copy and approve test budget corridor",
            })

        # Realistic default telemetry
        usage = ModelUsage(
            prompt_tokens=1500 + len(prompt_text) // 10,
            completion_tokens=2500 + len(content_str) // 10,
            thoughts_tokens=850,
            cached_tokens=None,
            tool_use_prompt_tokens=None,
            total_tokens=4850,
            usage_source="PROVIDER_REPORTED",
        )

        return ModelResponse(
            request_id=request.request_id,
            provider="gemini",
            model_name=request.model_name or self._default_model,
            status=ModelResponseStatus.SUCCESS,
            content=content_str,
            usage=usage,
            latency_ms=125.0,
            finish_reason="stop",
        )
