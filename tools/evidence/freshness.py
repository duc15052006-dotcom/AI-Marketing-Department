"""Deterministic Evidence Freshness Evaluator (Phase 3D.0 / 3D.1 Hardened).

Calculates temporal decay and freshness states based on source capability and publication dates.
Avoids universal blunt age thresholds by applying capability-specific temporal decay models
or explicit task/domain FreshnessPolicy overrides.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple, Union
from tools.evidence.models import FreshnessPolicy, FreshnessPolicySource, FreshnessState


class FreshnessEvaluator:
    """Evaluates evidence freshness deterministically based on source type, policy, and elapsed days."""

    # Days thresholds: (CURRENT_MAX_DAYS, RECENT_MAX_DAYS)
    DEFAULT_CAPABILITY_THRESHOLDS = {
        "pricing": (7.0, 30.0),
        "search_web": (30.0, 90.0),
        "read_forum_thread": (30.0, 90.0),
        "search_public_discussions": (30.0, 90.0),
        "youtube_metadata": (60.0, 180.0),
        "read_transcript": (60.0, 180.0),
        "read_page": (90.0, 365.0),
        "analyze_url": (90.0, 365.0),
        "encyclopedic": (365.0, 730.0),
    }
    DEFAULT_THRESHOLDS = (60.0, 180.0)

    @classmethod
    def evaluate(
        cls,
        capability: str,
        collected_at: Union[datetime, str],
        observed_at: Optional[Union[datetime, str]] = None,
        now: Optional[datetime] = None,
        custom_policy: Optional[FreshnessPolicy] = None,
    ) -> Tuple[FreshnessState, Optional[float], FreshnessPolicySource]:
        """Compute freshness state, elapsed days, and policy provenance."""
        current_time = now or datetime.now(timezone.utc)
        raw_ref = observed_at or collected_at

        if not raw_ref:
            return FreshnessState.UNKNOWN, None, FreshnessPolicySource.DEFAULT_HEURISTIC

        if isinstance(raw_ref, str):
            try:
                reference_time = datetime.fromisoformat(raw_ref.replace("Z", "+00:00"))
            except Exception:
                return FreshnessState.UNKNOWN, None, FreshnessPolicySource.DEFAULT_HEURISTIC
        else:
            reference_time = raw_ref

        # Ensure timezone-aware
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        elapsed_seconds = (current_time - reference_time).total_seconds()
        elapsed_days = max(0.0, elapsed_seconds / 86400.0)

        if custom_policy:
            current_thresh = custom_policy.current_max_days
            recent_thresh = custom_policy.recent_max_days
            policy_source = custom_policy.policy_source
        else:
            current_thresh, recent_thresh = cls.DEFAULT_CAPABILITY_THRESHOLDS.get(
                capability, cls.DEFAULT_THRESHOLDS
            )
            policy_source = FreshnessPolicySource.DEFAULT_HEURISTIC

        if elapsed_days <= current_thresh:
            state = FreshnessState.CURRENT
        elif elapsed_days <= recent_thresh:
            state = FreshnessState.RECENT
        else:
            state = FreshnessState.STALE

        return state, round(elapsed_days, 2), policy_source
