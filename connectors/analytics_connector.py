"""Deterministic analytics and KPI connector.

No synthetic attribution weights, p-values, confidence intervals, or campaign
telemetry are produced.  Retrieval succeeds only for data that has actually
been ingested; computations succeed only from explicit numeric inputs.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List

from schemas.base import BaseModel
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


class CampaignMetric(BaseModel):
    metric_id: str
    campaign_id: str
    channel: str
    date_window: str
    impressions: int = 0
    reach: int = 0
    clicks: int = 0
    conversions: int = 0
    spend: float = 0.0
    revenue: float = 0.0
    engagement_count: int = 0
    video_views: int = 0

    @property
    def ctr(self) -> float:
        return (self.clicks / self.impressions) if self.impressions > 0 else 0.0

    @property
    def cpc(self) -> float:
        return (self.spend / self.clicks) if self.clicks > 0 else 0.0

    @property
    def cpm(self) -> float:
        return (self.spend / (self.impressions / 1000.0)) if self.impressions > 0 else 0.0

    @property
    def cvr(self) -> float:
        return (self.conversions / self.clicks) if self.clicks > 0 else 0.0

    @property
    def cpa(self) -> float:
        return (self.spend / self.conversions) if self.conversions > 0 else 0.0

    @property
    def roas(self) -> float:
        return (self.revenue / self.spend) if self.spend > 0 else 0.0


class RealAnalyticsConnector(BaseCapabilityAdapter):
    """In-memory real-data analytics connector with deterministic computation."""

    def __init__(self) -> None:
        self._metrics_store: Dict[str, List[CampaignMetric]] = {}

    @property
    def adapter_name(self) -> str:
        return "local_analytics"

    def ingest_campaign_metrics(self, campaign_id: str, raw_records: List[Dict[str, Any]]) -> int:
        metrics: List[CampaignMetric] = []
        for idx, rec in enumerate(raw_records):
            metrics.append(CampaignMetric(
                metric_id=f"METRIC-{campaign_id}-{idx + 1}",
                campaign_id=campaign_id,
                channel=str(rec.get("channel") or "unknown"),
                date_window=str(rec.get("date_window") or "unspecified"),
                impressions=max(0, int(rec.get("impressions", 0))),
                reach=max(0, int(rec.get("reach", 0))),
                clicks=max(0, int(rec.get("clicks", 0))),
                conversions=max(0, int(rec.get("conversions", 0))),
                spend=max(0.0, float(rec.get("spend", 0.0))),
                revenue=max(0.0, float(rec.get("revenue", 0.0))),
                engagement_count=max(0, int(rec.get("engagement_count", 0))),
                video_views=max(0, int(rec.get("video_views", 0))),
            ))
        self._metrics_store[campaign_id] = metrics
        return len(metrics)

    def _failure(self, start: float, code: str, message: str) -> AdapterResult:
        return AdapterResult(
            success=False,
            error_code=code,
            error_message=message,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.REAL,
        )

    def execute(
        self,
        capability_id: str,
        parameters: Dict[str, Any],
        timeout_seconds: float = 15.0,
        *,
        run_id: str = "",
        business_id: str = "",
        project_id: str = "",
    ) -> AdapterResult:
        start = time.perf_counter()
        cap = capability_id.lower()
        campaign_id = str(parameters.get("campaign_id") or "CAMP_DEFAULT")

        if cap == "analytics_retrieval":
            metrics = self._metrics_store.get(campaign_id, [])
            if not metrics:
                return self._failure(start, "NO_DATA", f"No campaign telemetry ingested for '{campaign_id}'.")
            totals = {
                "impressions": sum(m.impressions for m in metrics),
                "clicks": sum(m.clicks for m in metrics),
                "conversions": sum(m.conversions for m in metrics),
                "spend": sum(m.spend for m in metrics),
                "revenue": sum(m.revenue for m in metrics),
            }
            imp, clk, conv, spend, revenue = (
                totals["impressions"], totals["clicks"], totals["conversions"], totals["spend"], totals["revenue"]
            )
            data = {
                "campaign_id": campaign_id,
                **totals,
                "ctr": (clk / imp) if imp > 0 else None,
                "cpc": (spend / clk) if clk > 0 else None,
                "cvr": (conv / clk) if clk > 0 else None,
                "cpa": (spend / conv) if conv > 0 else None,
                "roas": (revenue / spend) if spend > 0 else None,
                "data_origin": "INGESTED_TELEMETRY",
            }
            return AdapterResult(success=True, data=data, latency_ms=(time.perf_counter() - start) * 1000.0, execution_mode=ExecutionMode.REAL)

        if cap == "kpi_calculation":
            spend_raw = parameters.get("spend")
            revenue_raw = parameters.get("revenue")
            clicks_raw = parameters.get("clicks")
            conversions_raw = parameters.get("conversions")
            if spend_raw is None or (revenue_raw is None and clicks_raw is None and conversions_raw is None):
                return self._failure(start, "MISSING_INPUTS", "Explicit numeric inputs are required for KPI calculation.")
            try:
                spend = float(spend_raw)
                revenue = float(revenue_raw) if revenue_raw is not None else None
                clicks = int(clicks_raw) if clicks_raw is not None else None
                conversions = int(conversions_raw) if conversions_raw is not None else None
            except (TypeError, ValueError):
                return self._failure(start, "INVALID_INPUTS", "KPI inputs must be valid numeric values.")
            if spend < 0 or (revenue is not None and revenue < 0) or (clicks is not None and clicks < 0) or (conversions is not None and conversions < 0):
                return self._failure(start, "INVALID_INPUTS", "KPI inputs cannot be negative.")
            data = {
                "metric": str(parameters.get("metric_name") or "derived_kpis"),
                "roas": (revenue / spend) if revenue is not None and spend > 0 else None,
                "cac": (spend / conversions) if conversions is not None and conversions > 0 else None,
                "cvr": (conversions / clicks) if conversions is not None and clicks is not None and clicks > 0 else None,
                "cpc": (spend / clicks) if clicks is not None and clicks > 0 else None,
                "data_origin": "EXPLICIT_INPUT_COMPUTATION",
            }
            return AdapterResult(success=True, data=data, latency_ms=(time.perf_counter() - start) * 1000.0, execution_mode=ExecutionMode.REAL)

        if cap == "attribution_data_access":
            # Attribution is observational data, never something this connector invents.
            weights = parameters.get("channel_weights")
            if not isinstance(weights, dict) or not weights:
                return self._failure(start, "NO_ATTRIBUTION_DATA", "No measured attribution dataset was supplied or ingested.")
            try:
                normalized = {str(k): float(v) for k, v in weights.items()}
            except (TypeError, ValueError):
                return self._failure(start, "INVALID_ATTRIBUTION_DATA", "Attribution weights must be numeric.")
            if any(v < 0 for v in normalized.values()):
                return self._failure(start, "INVALID_ATTRIBUTION_DATA", "Attribution weights cannot be negative.")
            total = sum(normalized.values())
            if not (0.999 <= total <= 1.001):
                return self._failure(start, "INVALID_ATTRIBUTION_DATA", "Attribution weights must sum to 1.0.")
            return AdapterResult(
                success=True,
                data={"channel_weights": normalized, "data_origin": "EXPLICIT_MEASURED_INPUT"},
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.REAL,
            )

        if cap == "experiment_result_analysis":
            required = ("control_conversions", "control_sample_size", "variant_conversions", "variant_sample_size")
            if any(parameters.get(k) is None for k in required):
                return self._failure(start, "MISSING_EXPERIMENT_DATA", "Control and variant conversions/sample sizes are required.")
            try:
                cc = int(parameters["control_conversions"])
                cn = int(parameters["control_sample_size"])
                vc = int(parameters["variant_conversions"])
                vn = int(parameters["variant_sample_size"])
            except (TypeError, ValueError):
                return self._failure(start, "INVALID_EXPERIMENT_DATA", "Experiment counts must be integers.")
            if cn <= 0 or vn <= 0 or min(cc, vc) < 0 or cc > cn or vc > vn:
                return self._failure(start, "INVALID_EXPERIMENT_DATA", "Experiment counts are outside valid bounds.")
            p1, p2 = cc / cn, vc / vn
            pooled = (cc + vc) / (cn + vn)
            se = math.sqrt(max(0.0, pooled * (1.0 - pooled) * (1.0 / cn + 1.0 / vn)))
            if se == 0.0:
                p_value = 1.0 if p1 == p2 else 0.0
            else:
                z = (p2 - p1) / se
                p_value = math.erfc(abs(z) / math.sqrt(2.0))
            return AdapterResult(
                success=True,
                data={
                    "control_rate": p1,
                    "variant_rate": p2,
                    "absolute_lift": p2 - p1,
                    "p_value_two_sided": p_value,
                    "sample_sizes": {"control": cn, "variant": vn},
                    "data_origin": "EXPLICIT_EXPERIMENT_INPUT",
                },
                latency_ms=(time.perf_counter() - start) * 1000.0,
                execution_mode=ExecutionMode.REAL,
            )

        return self._failure(start, "UNSUPPORTED_CAPABILITY", f"Capability '{capability_id}' is not handled by RealAnalyticsConnector.")
