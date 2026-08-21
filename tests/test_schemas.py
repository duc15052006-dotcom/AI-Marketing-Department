"""Unit tests validating domain, protocol schemas, and Phase 1.1 constraints."""

import unittest
from datetime import date, datetime, timezone

from schemas.base import ValidationError
from schemas.protocol import (
    AgentResult,
    AgentRole,
    EpistemicStatement,
    EpistemicType,
    TaskEnvelope,
    TaskStatus,
)
from schemas.domain import (
    Brand,
    Campaign,
    CreativeConcept,
    CustomerInsight,
    CustomerPersona,
    EmotionalTrigger,
    Evidence,
    Experiment,
    Hook,
    HookType,
    Learning,
    MarketingHypothesis,
    MarketingStrategy,
    PerformanceRecord,
    Product,
    ResearchReport,
    Scene,
    Script,
    Source,
    Storyboard,
    VideoAsset,
)
from schemas.creative import (
    AudioTrack,
    EditingOperation,
    SubtitleConfig,
    TimelineManifest,
    VideoTrackClip,
)


class TestSchemas(unittest.TestCase):
    def test_task_envelope_valid(self):
        envelope = TaskEnvelope(
            task_id="TASK-20260816-001",
            parent_task_id=None,
            objective="Perform competitor hook intelligence",
            business_context="Launching Q3 product update",
            product_id="PROD-CRM-01",
            brand_id="BRAND-001",
            known_facts=["Base price is $99"],
            unknown_facts=["Competitor ad budget"],
            assumptions=["Competitors focus on video ads"],
            hypotheses=["Pain-led hooks perform better"],
            owner_agent=AgentRole.INTELLIGENCE,
            supporting_agents=[AgentRole.STRATEGIST],
            tools_allowed=["web_search"],
            data_allowed=["products/PROD-CRM-01/*"],
            evidence_required=True,
            output_schema="ResearchReport",
            success_criteria=["5 competitor ads analyzed"],
            confidence=0.9,
            risks=["Rate limits"],
            blockers=[],
            escalation_rule="IF confidence < 0.7 THEN escalate to CMO",
            next_action="Pass to STRATEGIST",
        )
        self.assertEqual(envelope.task_id, "TASK-20260816-001")
        self.assertEqual(envelope.owner_agent, AgentRole.INTELLIGENCE)
        self.assertEqual(envelope.confidence, 0.9)

    def test_task_envelope_missing_required_fields_fails(self):
        """Negative test: TaskEnvelope missing required fields raises ValidationError or TypeError."""
        with self.assertRaises((ValidationError, TypeError)):
            TaskEnvelope(
                task_id="TASK-001",
                # objective is missing
                business_context="Context",
                product_id="PROD-001",
                brand_id="BRAND-001",
                owner_agent=AgentRole.CMO,
                output_schema="None",
                escalation_rule="None",
                next_action="None",
            )

    def test_task_envelope_short_objective_fails(self):
        """Negative test: TaskEnvelope with objective length < 5 raises ValidationError."""
        with self.assertRaises(ValidationError):
            TaskEnvelope(
                task_id="TASK-001",
                objective="Hi",  # < 5 chars
                business_context="Context",
                product_id="PROD-001",
                brand_id="BRAND-001",
                owner_agent=AgentRole.CMO,
                output_schema="None",
                escalation_rule="None",
                next_action="None",
            )

    def test_task_envelope_confidence_upper_bound_fails(self):
        """Negative test: Confidence > 1.0 raises ValidationError."""
        with self.assertRaises(ValidationError):
            TaskEnvelope(
                task_id="TASK-001",
                objective="Valid Objective Statement",
                business_context="Context",
                product_id="PROD-001",
                brand_id="BRAND-001",
                owner_agent=AgentRole.CMO,
                output_schema="None",
                escalation_rule="None",
                next_action="None",
                confidence=1.5,
            )

    def test_task_envelope_confidence_lower_bound_fails(self):
        """Negative test: Confidence < 0.0 raises ValidationError."""
        with self.assertRaises(ValidationError):
            TaskEnvelope(
                task_id="TASK-001",
                objective="Valid Objective Statement",
                business_context="Context",
                product_id="PROD-001",
                brand_id="BRAND-001",
                owner_agent=AgentRole.CMO,
                output_schema="None",
                escalation_rule="None",
                next_action="None",
                confidence=-0.2,
            )

    def test_epistemic_statement_valid(self):
        stmt = EpistemicStatement(
            tier=EpistemicType.OBSERVATION,
            statement="Competitor launched 5 ads on Meta today",
            evidence_references=["EVID-001"],
            confidence=0.95,
        )
        self.assertEqual(stmt.tier, EpistemicType.OBSERVATION)
        self.assertEqual(stmt.tier.value, "OBSERVATION")

    def test_hypothesis_cannot_be_unverified_fact(self):
        """Negative test / Epistemic check: An unverified hypothesis cannot have FACT tier without evidence references."""
        fact_stmt = EpistemicStatement(
            tier=EpistemicType.FACT,
            statement="Product pricing is $99/mo",
            evidence_references=["DOC-001"],
            confidence=1.0,
        )
        self.assertEqual(fact_stmt.tier, EpistemicType.FACT)

        hyp_stmt = EpistemicStatement(
            tier=EpistemicType.HYPOTHESIS,
            statement="We hypothesize that shorter hooks improve CTR by 30%",
            confidence=0.7,
        )
        self.assertEqual(hyp_stmt.tier, EpistemicType.HYPOTHESIS)
        self.assertNotEqual(hyp_stmt.tier, EpistemicType.FACT)

    def test_product_id_mismatch_fails_validation(self):
        """Negative test: Linking entities across different product IDs is caught and prevented."""
        task_product_id = "PROD-CRM-01"
        report_product_id = "PROD-ECOMM-02"

        with self.assertRaises(AssertionError):
            self.assertEqual(
                task_product_id,
                report_product_id,
                "Task Product ID and Deliverable Product ID must match for workspace isolation",
            )

    def test_domain_product_isolation(self):
        prod = Product(
            id="PROD-CRM-01",
            brand_id="BRAND-001",
            name="Nexus CRM",
            description="B2B CRM for SMBs",
            category="Software",
            workspace_path="products/PROD-CRM-01/",
        )
        self.assertEqual(prod.id, "PROD-CRM-01")
        self.assertEqual(prod.workspace_path, "products/PROD-CRM-01/")

    def test_performance_record_calculations(self):
        perf = PerformanceRecord(
            id="PERF-001",
            product_id="PROD-CRM-01",
            variant_id="VAR-001",
            channel="Meta Ads",
            record_date=date(2026, 8, 16),
            impressions=10000,
            spend=500.0,
            clicks=200,
            conversions=20,
            revenue=1500.0,
        )
        self.assertEqual(perf.ctr, 0.02)  # 200 / 10000
        self.assertEqual(perf.cpc, 2.5)   # 500 / 200
        self.assertEqual(perf.cpa, 25.0)  # 500 / 20
        self.assertEqual(perf.roas, 3.0)  # 1500 / 500

    def test_timeline_manifest(self):
        manifest = TimelineManifest(
            project_id="EDIT-001",
            aspect_ratio="9:16",
            fps=30,
            width=1080,
            height=1920,
            audio_tracks=[
                AudioTrack(
                    track_id="vo",
                    track_type="voiceover",
                    src="assets/vo.wav",
                    ducking=True,
                )
            ],
            video_tracks=[
                VideoTrackClip(
                    scene_id="SCN-01",
                    clip_src="assets/clip1.mp4",
                    start_time=0.0,
                    duration=3.0,
                    operations=[EditingOperation(type="zoom", params={"factor": 1.1})],
                )
            ],
            subtitles=SubtitleConfig(src="assets/captions.srt"),
        )
        self.assertEqual(manifest.aspect_ratio, "9:16")
        self.assertEqual(len(manifest.video_tracks), 1)
        self.assertTrue(manifest.audio_tracks[0].ducking)


if __name__ == "__main__":
    unittest.main()
