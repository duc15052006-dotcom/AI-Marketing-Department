"""Real Analytics and KPI Connector (Phase 6.1).

Implements real campaign metric ingestion, structured CampaignMetric records,
and deterministic KPI calculations for Performance and Strategist agents.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from schemas.base import BaseModel, Field
from tools.adapters import AdapterResult, BaseCapabilityAdapter
from tools.receipts import ExecutionMode


class CampaignMetric(BaseModel):
    """Normalized campaign performance record."""
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
    """Real analytics ingestion and calculation connector."""

    def __init__(self) -> None:
        self._metrics_store: Dict[str, List[CampaignMetric]] = {}

    @property
    def adapter_name(self) -> str:
        return "local_analytics"

    def execution_mode_for(self, capability_id: str) -> ExecutionMode:
        """Declare REAL provenance only for reads of the ingested analytics store."""
        return ExecutionMode.REAL if capability_id.lower() == "analytics_retrieval" else ExecutionMode.MOCK

    def ingest_campaign_metrics(self, campaign_id: str, raw_records: List[Dict[str, Any]]) -> int:
        """Ingest raw structured campaign records into normalized CampaignMetrics."""
        metrics = []
        for idx, rec in enumerate(raw_records):
            metric = CampaignMetric(
                metric_id=f"METRIC-{campaign_id}-{idx+1}",
                campaign_id=campaign_id,
                channel=rec.get("channel", "paid_social"),
                date_window=rec.get("date_window", "last_30_days"),
                impressions=int(rec.get("impressions", 0)),
                reach=int(rec.get("reach", 0)),
                clicks=int(rec.get("clicks", 0)),
                conversions=int(rec.get("conversions", 0)),
                spend=float(rec.get("spend", 0.0)),
                revenue=float(rec.get("revenue", 0.0)),
            )
            metrics.append(metric)
        self._metrics_store[campaign_id] = metrics
        return len(metrics)

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
        start_time = time.perf_counter()
        cap = capability_id.lower()
        campaign_id = parameters.get("campaign_id", "CAMP_DEFAULT")

        if cap == "analytics_retrieval":
            metrics = self._metrics_store.get(campaign_id, [])
            if not metrics:
                return AdapterResult(
                    success=False,
                    error_code="NO_DATA",
                    error_message=f"No campaign telemetry ingested for '{campaign_id}'.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )
            tot_imp = sum(m.impressions for m in metrics)
            tot_clk = sum(m.clicks for m in metrics)
            tot_conv = sum(m.conversions for m in metrics)
            tot_spd = sum(m.spend for m in metrics)
            tot_rev = sum(m.revenue for m in metrics)
            metric_data = {
                "campaign_id": campaign_id,
                "impressions": tot_imp,
                "clicks": tot_clk,
                "conversions": tot_conv,
                "spend": tot_spd,
                "revenue": tot_rev,
                "ctr": (tot_clk / tot_imp) if tot_imp > 0 else 0.0,
                "cpc": (tot_spd / tot_clk) if tot_clk > 0 else 0.0,
                "cvr": (tot_conv / tot_clk) if tot_clk > 0 else 0.0,
                "cpa": (tot_spd / tot_conv) if tot_conv > 0 else 0.0,
                "roas": (tot_rev / tot_spd) if tot_spd > 0 else 0.0,
            }

            return AdapterResult(
                success=True,
                data=metric_data,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.REAL,
            )

        elif cap == "kpi_calculation":
            metric_name = parameters.get("metric_name", "roas")
            spend_raw = parameters.get("spend")
            revenue_raw = parameters.get("revenue")
            clicks_raw = parameters.get("clicks")
            conversions_raw = parameters.get("conversions")

            if spend_raw is None or (revenue_raw is None and clicks_raw is None and conversions_raw is None):
                return AdapterResult(
                    success=False,
                    error_code="MISSING_INPUTS",
                    error_message="Explicit inputs (e.g. 'spend', 'revenue') are required for KPI calculation.",
                    latency_ms=(time.perf_counter() - start_time) * 1000.0,
                    execution_mode=ExecutionMode.MOCK,
                )

            spend = float(spend_raw)
            revenue = float(revenue_raw) if revenue_raw is not None else 0.0
            clicks = int(clicks_raw) if clicks_raw is not None else 0
            conversions = int(conversions_raw) if conversions_raw is not None else 0

            calc_result = {
                "metric": metric_name,
                "roas": (revenue / spend) if spend > 0 else 0.0,
                "cac": (spend / conversions) if conversions > 0 else 0.0,
                "cvr": (conversions / clicks) if clicks > 0 else 0.0,
                "cpc": (spend / clicks) if clicks > 0 else 0.0,
            }
            return AdapterResult(
                success=True,
                data=calc_result,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        elif cap in ("attribution_data_access", "experiment_result_analysis"):
            # The connector call itself is available, but without observed inputs
            # there is no analytic result to report. Keep the legacy MOCK-success
            # capability contract while returning only an explicit no-data state;
            # never invent weights, winners, significance, p-values, or metrics.
            return AdapterResult(
                success=True,
                data={
                    "analysis_available": False,
                    "status": "NO_OBSERVED_DATA",
                    "capability": cap,
                    "required_action": "Provide observed attribution/experiment data before analysis.",
                },
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )

        return AdapterResult(
            success=False,
            error_code="UNSUPPORTED_CAPABILITY",
            error_message=f"Capability '{capability_id}' not handled by RealAnalyticsConnector.",
            latency_ms=(time.perf_counter() - start_time) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )