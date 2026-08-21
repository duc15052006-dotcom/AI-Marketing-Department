"""Token and Cost Governance Tracker.

Tracks invocation counts, token usage, and locally estimated costs.
Explicitly separates provider-reported billing truth from local estimates.
Enforces budget ceilings to prevent runaway agent loops.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from schemas.base import BaseModel, Field
from integrations.models.base import ModelUsage


class CostGovernanceConfig(BaseModel):
    """Budget constraints and pricing configuration."""
    max_model_calls: int = Field(default=25, description="Maximum allowed model invocations in workflow")
    max_token_budget: int = Field(default=100_000, description="Maximum total tokens across workflow")
    max_cost_budget_usd: Optional[float] = Field(default=5.00, description="Maximum allowed estimated spend in USD")

    # Estimated pricing per 1M tokens in USD
    pricing_per_1m_prompt: Dict[str, float] = Field(
        default_factory=lambda: {
            "gemini-1.5-pro": 3.50,
            "gemini-1.5-flash": 0.35,
            "gpt-4o": 5.00,
            "gpt-4o-mini": 0.15,
            "gpt-5.6-sol": 1.50,
            "default": 1.00,
        }
    )
    pricing_per_1m_completion: Dict[str, float] = Field(
        default_factory=lambda: {
            "gemini-1.5-pro": 10.50,
            "gemini-1.5-flash": 1.05,
            "gpt-4o": 15.00,
            "gpt-4o-mini": 0.60,
            "gpt-5.6-sol": 3.00,
            "default": 3.00,
        }
    )


class CostTracker:
    """Tracks token consumption and enforces cost limits with explicit provenance separation."""

    def __init__(self, config: Optional[CostGovernanceConfig] = None) -> None:
        self.config = config or CostGovernanceConfig()
        self.total_calls: int = 0
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.total_tokens: int = 0
        self.local_estimated_cost_usd: float = 0.0
        self.provider_reported_cost_usd: Optional[float] = None
        self.pricing_source: str = "ESTIMATED_PUBLIC_RATES"
        self.estimate_limitations: str = (
            "Local estimate calculated from token counters and reference pricing tables. "
            "Provider billing may reflect custom tiers, minimums, or multiplier surcharges."
        )

    def record_usage(
        self,
        model_name: str,
        usage: ModelUsage,
        provider_cost: Optional[float] = None,
    ) -> None:
        """Record model execution usage and update running cost estimates."""
        self.total_calls += 1
        self.total_prompt_tokens += usage.prompt_tokens
        self.total_completion_tokens += usage.completion_tokens
        self.total_tokens += usage.total_tokens

        prompt_rate = self.config.pricing_per_1m_prompt.get(
            model_name, self.config.pricing_per_1m_prompt.get("default", 1.00)
        )
        comp_rate = self.config.pricing_per_1m_completion.get(
            model_name, self.config.pricing_per_1m_completion.get("default", 3.00)
        )

        cost = (
            (usage.prompt_tokens / 1_000_000.0) * prompt_rate
            + (usage.completion_tokens / 1_000_000.0) * comp_rate
        )
        self.local_estimated_cost_usd += cost

        if provider_cost is not None:
            self.provider_reported_cost_usd = provider_cost

    def check_budget_limits(self) -> None:
        """Check if any budget constraints are breached; raise exception if exceeded."""
        if self.total_calls >= self.config.max_model_calls:
            raise RuntimeError(
                f"BUDGET_BREACH: Maximum model calls exceeded ({self.total_calls} >= {self.config.max_model_calls})."
            )
        if self.total_tokens >= self.config.max_token_budget:
            raise RuntimeError(
                f"BUDGET_BREACH: Maximum token budget exceeded ({self.total_tokens} >= {self.config.max_token_budget})."
            )
        if (
            self.config.max_cost_budget_usd is not None
            and self.local_estimated_cost_usd >= self.config.max_cost_budget_usd
        ):
            raise RuntimeError(
                f"BUDGET_BREACH: Maximum cost budget exceeded (${self.local_estimated_cost_usd:.4f} >= ${self.config.max_cost_budget_usd:.2f})."
            )

    def summary(self) -> Dict[str, Any]:
        """Return structured summary separating local estimates from provider-reported cost."""
        return {
            "model_calls": self.total_calls,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "local_estimated_cost_usd": round(self.local_estimated_cost_usd, 6),
            "provider_reported_cost_usd": self.provider_reported_cost_usd,
            "pricing_source": self.pricing_source,
            "estimate_limitations": self.estimate_limitations,
        }
