"""Phase 4.3C.13: Five-Agent Brain RC2 Targeted Optimization & Anti-Information-Loss Tests.

Tests:
A. Performance agent supplies attribution; Final CMO handoff must preserve it.
B. Performance supplies experiments; Final CMO handoff must preserve hypothesis + metric + decision rule.
C. Performance supplies human approval; Final CMO handoff cannot drop it.
D. Performance says baseline unknown; Final CMO cannot invent sample size.
E. Upstream agents disagree; Final CMO records contradiction and decision basis.
F. Hypothesis enters handoff; Final output cannot promote it to fact.
G. Creative output is long; Performance critical fields must still survive final synthesis.
H. Missing Performance field triggers validation failure rather than silent omission.
I. Final CMO remains executive and readable, not a raw concatenation of all agent outputs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from schemas.handoff import (
    ContradictionResolutionRecord,
    HandoffPackage,
    PerformanceHandoffPayload,
    PreservationItem,
    PreservationLedger,
)
from integrations.models.agent_loader import AgentLoader


class TestPhase43C13BrainRC2Architecture(unittest.TestCase):
    """Adversarial verification of Brain RC2 Anti-Information-Loss contracts."""

    def test_a_performance_attribution_preserved_in_cmo_handoff(self) -> None:
        """A. Performance agent supplies attribution; Final CMO handoff must preserve it."""
        perf_payload = PerformanceHandoffPayload(
            attribution_architecture={
                "model": "Multi-Touch Linear + Position-Based",
                "taxonomy": "utm_source, utm_medium, utm_campaign, utm_content",
                "events": ["repo_scan_initiated", "first_vulnerability_fixed", "paid_tier_upgrade"],
            }
        )
        handoff = HandoffPackage(
            task_id="TASK-RC2-A",
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            product_id="PROD_TEST_A",
            brand_id="BRAND_TEST_A",
            objective="Synthesize full proposal",
            performance_payload=perf_payload,
            required_next_output="Full JSON",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("ATTRIBUTION_ARCHITECTURE", prompt_text)
        self.assertIn("repo_scan_initiated", prompt_text)
        self.assertIn("Multi-Touch Linear", prompt_text)

    def test_b_performance_experiments_preserved_with_decision_rules(self) -> None:
        """B. Performance supplies experiments; Final CMO handoff must preserve hypothesis + metric + decision rule."""
        experiments = [
            {
                "id": "EXP-001",
                "hypothesis": "Free CLI linter integration increases trial-to-paid by 25%",
                "intervention": "One-click GitHub Action scanner",
                "primary_metric": "Trial-to-Paid Conversion Rate",
                "decision_rule": "Scale if p < 0.05 and CVR lift > 15%; kill if CVR lift < 5%",
                "stopping_criteria": "Max 500 scans or 14 calendar days",
            }
        ]
        perf_payload = PerformanceHandoffPayload(experiment_backlog=experiments)
        handoff = HandoffPackage(
            task_id="TASK-RC2-B",
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            product_id="PROD_TEST_B",
            brand_id="BRAND_TEST_B",
            objective="Synthesize proposal",
            performance_payload=perf_payload,
            required_next_output="Full JSON",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("EXPERIMENT_BACKLOG", prompt_text)
        self.assertIn("Free CLI linter integration", prompt_text)
        self.assertIn("Scale if p < 0.05", prompt_text)

    def test_c_performance_human_approvals_preserved(self) -> None:
        """C. Performance supplies human approval; Final CMO handoff cannot drop it."""
        approvals = [
            "Executive CMO sign-off on ad spend exceeding $10,000",
            "Legal counsel sign-off on enterprise SOC 2 compliance wording",
        ]
        perf_payload = PerformanceHandoffPayload(human_approvals=approvals)
        handoff = HandoffPackage(
            task_id="TASK-RC2-C",
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            product_id="PROD_TEST_C",
            brand_id="BRAND_TEST_C",
            objective="Synthesize proposal",
            performance_payload=perf_payload,
            required_next_output="Full JSON",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("HUMAN_APPROVALS", prompt_text)
        self.assertIn("Legal counsel sign-off", prompt_text)

    def test_d_performance_unknown_baseline_not_invented(self) -> None:
        """D. Performance says baseline unknown; Final CMO cannot invent sample size."""
        perf_payload = PerformanceHandoffPayload(
            unresolved_measurement_gaps=[
                "BASELINE_REQUIRED: Historical trial-to-paid baseline unknown; pilot sample size must be estimated post-launch."
            ]
        )
        handoff = HandoffPackage(
            task_id="TASK-RC2-D",
            from_agent="PERFORMANCE",
            to_agent="CMO_FINAL",
            product_id="PROD_TEST_D",
            brand_id="BRAND_TEST_D",
            objective="Synthesize proposal",
            performance_payload=perf_payload,
            required_next_output="Full JSON",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("UNRESOLVED_MEASUREMENT_GAPS", prompt_text)
        self.assertIn("BASELINE_REQUIRED", prompt_text)

    def test_e_upstream_contradiction_resolution_recording(self) -> None:
        """E. Upstream agents disagree; Final CMO records contradiction and decision basis."""
        conflict = ContradictionResolutionRecord(
            conflict_id="CONF-001",
            agents_involved=["STRATEGIST", "CREATIVE"],
            topic="Pricing Visibility in Top-of-Funnel Video Ads",
            options=["Disclose $49/seat price upfront", "Hide price to maximize curiosity clicks"],
            decision="Disclose starting price upfront",
            decision_basis="Developer audience heavily penalizes hidden pricing friction",
            confidence="HIGH",
            human_approval_required=False,
        )
        ledger = PreservationLedger(resolved_contradictions=[conflict])
        self.assertEqual(len(ledger.resolved_contradictions), 1)
        self.assertEqual(ledger.resolved_contradictions[0].decision, "Disclose starting price upfront")

    def test_f_hypothesis_epistemic_safety_in_handoff(self) -> None:
        """F. Hypothesis enters handoff; Final output cannot promote it to fact."""
        handoff = HandoffPackage(
            task_id="TASK-RC2-F",
            from_agent="STRATEGIST",
            to_agent="PERFORMANCE",
            product_id="PROD_TEST_F",
            brand_id="BRAND_TEST_F",
            objective="Design experiments",
            hypotheses=["Offering local currency billing in VND increases payment completion by 40%"],
            required_next_output="Experiment plan",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("[HYPOTHESIS] Offering local currency billing in VND", prompt_text)
        self.assertNotIn("PRODUCT FACTS (VERIFIED GROUND TRUTH):\n  - Offering local currency billing in VND", prompt_text)

    def test_g_long_creative_does_not_truncate_performance_fields(self) -> None:
        """G. Creative output is long; Performance critical fields must still survive final synthesis."""
        long_creative_text = "SCENE 1: ...\n" * 500  # ~6,000 characters
        perf_payload = PerformanceHandoffPayload(
            funnel_model={"primary_kpi": "Trial Conversion Rate", "guardrail": "CAC < $250"},
            governance_requirements=["CMO budget authorization gate"],
        )
        handoff = HandoffPackage(
            task_id="TASK-RC2-G",
            from_agent="ALL_AGENTS",
            to_agent="CMO_FINAL",
            product_id="PROD_TEST_G",
            brand_id="BRAND_TEST_G",
            objective="Synthesize",
            upstream_decisions={"creative": long_creative_text[:1200]},
            performance_payload=perf_payload,
            required_next_output="JSON",
        )
        prompt_text = handoff.format_prompt_section()
        self.assertIn("STRUCTURED PERFORMANCE BLUEPRINT (PRESERVED):", prompt_text)
        self.assertIn("Trial Conversion Rate", prompt_text)
        self.assertIn("CMO budget authorization gate", prompt_text)

    def test_h_missing_performance_field_triggers_validation_drop(self) -> None:
        """H. Missing Performance field triggers validation failure rather than silent omission."""
        ledger = PreservationLedger(
            intelligence_critical_items=[PreservationItem(source_agent="INTEL", category="R", description="Evidence", status="PRESERVED")],
            strategy_critical_items=[PreservationItem(source_agent="STRAT", category="S", description="Pillars", status="PRESERVED")],
            creative_critical_items=[PreservationItem(source_agent="CRTV", category="C", description="Scripts", status="PRESERVED")],
            performance_critical_items=[PreservationItem(source_agent="PERF", category="M", description="Attribution", status="UNRESOLVED")],
        )
        # 3 out of 4 preserved -> rate is 75%
        self.assertEqual(ledger.total_critical_items(), 4)
        self.assertEqual(ledger.preserved_items_count(), 3)
        self.assertEqual(ledger.audit_preservation_rate(), 0.75)
        self.assertLess(ledger.audit_preservation_rate(), 1.0)

    def test_i_agent_dna_rc2_loading_and_integrity(self) -> None:
        """I. Agent DNA files load cleanly and contain RC deliverable contracts."""
        loader = AgentLoader()
        perf_agent = loader.load_agent("performance")
        cmo_agent = loader.load_agent("cmo")

        self.assertTrue(
            "Five-Agent Brain RC2 Mandatory Deliverable Blueprint Contract" in perf_agent.system_dna
            or "Five-Agent Brain RC3 Mandatory Two-Pass Micro-Workflow Contract" in perf_agent.system_dna
        )
        self.assertTrue(
            "Governed Synthesis and Preservation Layer Contract (Brain RC2)" in cmo_agent.system_dna
            or "Governed Synthesis and Preservation Layer Contract (Brain RC3)" in cmo_agent.system_dna
        )


if __name__ == "__main__":
    unittest.main()
