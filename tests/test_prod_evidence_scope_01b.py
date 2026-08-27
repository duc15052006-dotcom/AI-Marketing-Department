"""EvidenceBundle + GroundingContext Scope Isolation Tests (PROD-RESEARCH-EVIDENCE-CONVERGENCE-01B-B1).

Validates that EvidenceBundle and GroundingContext enforce trusted scope isolation
for run_id, business_id, and project_id. No cross-run, cross-business, or
cross-project contamination is permitted.
"""

from datetime import datetime, timezone
import unittest
from tools.evidence.builder import EvidenceBuilder, ScopeViolationError, ProductIsolationViolationError
from tools.evidence.grounding import GroundingContextBuilder
from tools.evidence.models import EvidenceItem, ContentRole, SourceFamily


def _make_item(
    evidence_id: str = "EVID-001",
    product_id: str = "PROD-A",
    brand_id: str = "BRAND-A",
    run_id: str = "",
    business_id: str = "",
    project_id: str = "",
    source_url_or_id: str = "https://example.com",
) -> EvidenceItem:
    """Create a minimal EvidenceItem for testing."""
    return EvidenceItem(
        evidence_id=evidence_id,
        observation_id="OBS-001",
        capability="search_web",
        product_id=product_id,
        brand_id=brand_id,
        run_id=run_id,
        business_id=business_id,
        project_id=project_id,
        source_platform="web",
        source_type="search_result",
        source_url_or_id=source_url_or_id,
        backend_used="search_duckduckgo_html",
        collected_at=datetime.now(timezone.utc),
    )


class TestBundleScopeIsolation(unittest.TestCase):
    """EvidenceBundle scope isolation: run, business, project."""

    def test_run_mismatch_rejected(self):
        """Items with different run_id must be rejected."""
        item_a = _make_item("EVID-A", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_b = _make_item("EVID-B", run_id="RUN-B", business_id="BIZ-A", project_id="PROJ-A",
                            source_url_or_id="https://example.com/b")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_a, item_b],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_business_mismatch_rejected(self):
        """Items with different business_id must be rejected."""
        item_a = _make_item("EVID-A", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_b = _make_item("EVID-B", run_id="RUN-A", business_id="BIZ-B", project_id="PROJ-A",
                            source_url_or_id="https://example.com/b")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_a, item_b],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_project_mismatch_rejected(self):
        """Items with different project_id must be rejected."""
        item_a = _make_item("EVID-A", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_b = _make_item("EVID-B", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-B",
                            source_url_or_id="https://example.com/b")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_a, item_b],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_full_cross_scope_mismatch_rejected(self):
        """Items with all three scope fields different must be rejected."""
        item_a = _make_item("EVID-A", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_b = _make_item("EVID-B", run_id="RUN-B", business_id="BIZ-B", project_id="PROJ-B",
                            source_url_or_id="https://example.com/b")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_a, item_b],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_spoofed_evidence_scope_rejected(self):
        """Evidence with wrong scope is rejected even when expected scope is correct."""
        item_spoofed = _make_item(
            "EVID-SPOOF", run_id="RUN-B", business_id="BIZ-B", project_id="PROJ-B",
        )
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_spoofed],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_valid_same_scope_accepted(self):
        """Multiple items with matching scope are accepted."""
        item_a = _make_item("EVID-A", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_b = _make_item("EVID-B", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
                            source_url_or_id="https://example.com/b")
        item_c = _make_item("EVID-C", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
                            source_url_or_id="https://example.com/c")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item_a, item_b, item_c],
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        self.assertEqual(bundle.run_id, "RUN-A")
        self.assertEqual(bundle.business_id, "BIZ-A")
        self.assertEqual(bundle.project_id, "PROJ-A")
        self.assertEqual(len(bundle.evidence_items), 3)

    def test_generic_neutral_scope_accepted(self):
        """All-empty scope (generic/evaluation) is accepted."""
        item_a = _make_item("EVID-A", run_id="", business_id="", project_id="")
        item_b = _make_item("EVID-B", run_id="", business_id="", project_id="",
                            source_url_or_id="https://example.com/b")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item_a, item_b],
            run_id="", business_id="", project_id="",
        )
        self.assertEqual(bundle.run_id, "")
        self.assertEqual(bundle.business_id, "")
        self.assertEqual(bundle.project_id, "")

    def test_mixed_neutral_and_trusted_rejected(self):
        """Mixing empty scope with trusted scope must be rejected."""
        item_neutral = _make_item("EVID-NEUTRAL", run_id="", business_id="", project_id="")
        item_trusted = _make_item("EVID-TRUSTED", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
                                  source_url_or_id="https://example.com/trusted")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_neutral, item_trusted],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_mixed_trusted_and_neutral_rejected(self):
        """Mixing trusted scope with empty scope must be rejected (reverse order)."""
        item_trusted = _make_item("EVID-TRUSTED", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A")
        item_neutral = _make_item("EVID-NEUTRAL", run_id="", business_id="", project_id="",
                                  source_url_or_id="https://example.com/neutral")
        with self.assertRaises(ScopeViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_trusted, item_neutral],
                run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
            )

    def test_brand_business_distinct(self):
        """brand_id and business_id remain distinct fields."""
        item = _make_item(
            "EVID-001", product_id="PROD-Y", brand_id="BRAND-X",
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-Y", brand_id="BRAND-X",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        self.assertEqual(bundle.brand_id, "BRAND-X")
        self.assertEqual(bundle.business_id, "BIZ-A")
        self.assertNotEqual(bundle.brand_id, bundle.business_id)

    def test_product_project_distinct(self):
        """product_id and project_id remain distinct fields."""
        item = _make_item(
            "EVID-001", product_id="PROD-Y", brand_id="BRAND-X",
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-Y", brand_id="BRAND-X",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        self.assertEqual(bundle.product_id, "PROD-Y")
        self.assertEqual(bundle.project_id, "PROJ-A")
        self.assertNotEqual(bundle.product_id, bundle.project_id)

    def test_five_domain_dimensions_preserved(self):
        """All five scope dimensions survive unchanged on the bundle."""
        item = _make_item(
            "EVID-001", product_id="PROD-Y", brand_id="BRAND-X",
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-Y", brand_id="BRAND-X",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        self.assertEqual(bundle.product_id, "PROD-Y")
        self.assertEqual(bundle.brand_id, "BRAND-X")
        self.assertEqual(bundle.run_id, "RUN-A")
        self.assertEqual(bundle.business_id, "BIZ-A")
        self.assertEqual(bundle.project_id, "PROJ-A")

    def test_scope_not_derived_from_brand_or_product(self):
        """Scope fields are independent of brand_id/product_id."""
        item = _make_item(
            "EVID-001", product_id="PROD-Y", brand_id="BRAND-X",
            run_id="RUN-123", business_id="BIZ-456", project_id="PROJ-789",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-Y", brand_id="BRAND-X",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-123", business_id="BIZ-456", project_id="PROJ-789",
        )
        self.assertNotEqual(bundle.run_id, bundle.brand_id)
        self.assertNotEqual(bundle.business_id, bundle.brand_id)
        self.assertNotEqual(bundle.project_id, bundle.product_id)

    def test_no_scope_args_allows_neutral_bundle(self):
        """Omitting scope args entirely allows neutral bundle (backward compat)."""
        item_a = _make_item("EVID-A", run_id="", business_id="", project_id="")
        item_b = _make_item("EVID-B", run_id="", business_id="", project_id="",
                            source_url_or_id="https://example.com/b")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item_a, item_b],
        )
        self.assertEqual(bundle.run_id, "")
        self.assertEqual(bundle.business_id, "")
        self.assertEqual(bundle.project_id, "")


class TestGroundingContextScope(unittest.TestCase):
    """GroundingContext scope propagation from EvidenceBundle."""

    def test_grounding_context_scope_from_bundle(self):
        """GroundingContext inherits scope from EvidenceBundle exactly."""
        item = _make_item(
            "EVID-001", run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-A", business_id="BIZ-A", project_id="PROJ-A",
        )
        grounding = GroundingContextBuilder.build_grounding_context(
            bundle=bundle,
            task_description="Research task",
            business_context="Business context",
        )
        self.assertEqual(grounding.run_id, "RUN-A")
        self.assertEqual(grounding.business_id, "BIZ-A")
        self.assertEqual(grounding.project_id, "PROJ-A")
        self.assertEqual(grounding.product_id, "PROD-A")
        self.assertEqual(grounding.brand_id, "BRAND-A")

    def test_grounding_context_neutral_scope(self):
        """GroundingContext with neutral scope preserves empty strings."""
        item = _make_item("EVID-001", run_id="", business_id="", project_id="")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item],
            run_id="", business_id="", project_id="",
        )
        grounding = GroundingContextBuilder.build_grounding_context(
            bundle=bundle,
            task_description="Research task",
            business_context="Business context",
        )
        self.assertEqual(grounding.run_id, "")
        self.assertEqual(grounding.business_id, "")
        self.assertEqual(grounding.project_id, "")

    def test_grounding_context_scope_not_from_model_content(self):
        """GroundingContext scope comes from bundle, not from task/business_context text."""
        item = _make_item(
            "EVID-001", run_id="RUN-REAL", business_id="BIZ-REAL", project_id="PROJ-REAL",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=[item],
            run_id="RUN-REAL", business_id="BIZ-REAL", project_id="PROJ-REAL",
        )
        grounding = GroundingContextBuilder.build_grounding_context(
            bundle=bundle,
            task_description="Research about RUN-FAKE and BIZ-FAKE",
            business_context="Scope: PROJ-FAKE",
        )
        self.assertEqual(grounding.run_id, "RUN-REAL")
        self.assertEqual(grounding.business_id, "BIZ-REAL")
        self.assertEqual(grounding.project_id, "PROJ-REAL")


class TestExistingBehaviorPreserved(unittest.TestCase):
    """Ensure B1 changes do not break existing evidence behavior."""

    def test_product_isolation_still_works(self):
        """ProductIsolationViolationError still fires for cross-product."""
        item_a = _make_item("EVID-A", product_id="PROD-A", run_id="R", business_id="B", project_id="P")
        item_b = _make_item("EVID-B", product_id="PROD-B", run_id="R", business_id="B", project_id="P",
                            source_url_or_id="https://example.com/b")
        with self.assertRaises(ProductIsolationViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
                research_question="Q?", evidence_items=[item_a, item_b],
                run_id="R", business_id="B", project_id="P",
            )

    def test_evidence_items_retained_in_bundle(self):
        """Valid evidence items are all retained in the bundle."""
        items = [
            _make_item(f"EVID-{i}", run_id="R", business_id="B", project_id="P",
                       source_url_or_id=f"https://example.com/{i}")
            for i in range(5)
        ]
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Q?", evidence_items=items,
            run_id="R", business_id="B", project_id="P",
        )
        self.assertEqual(len(bundle.evidence_items), 5)

    def test_grounding_context_preserves_existing_fields(self):
        """GroundingContext still contains all existing fields."""
        item = _make_item("EVID-001", run_id="R", business_id="B", project_id="P")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="T1", product_id="PROD-A", brand_id="BRAND-A",
            research_question="Test question", evidence_items=[item],
            run_id="R", business_id="B", project_id="P",
        )
        grounding = GroundingContextBuilder.build_grounding_context(
            bundle=bundle,
            task_description="Research task",
            business_context="Business context",
        )
        self.assertEqual(grounding.task, "Research task")
        self.assertEqual(grounding.business_context, "Business context")
        self.assertEqual(grounding.evidence_bundle_reference, bundle.bundle_id)
        self.assertEqual(len(grounding.evidence_items), 1)
        self.assertEqual(grounding.product_id, "PROD-A")
        self.assertEqual(grounding.brand_id, "BRAND-A")


if __name__ == "__main__":
    unittest.main()
