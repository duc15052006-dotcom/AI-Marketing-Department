"""Deterministic Unit Tests for Evidence Integration Layer (Phase 3D.0 / 3D.1 / 3D.1.4).

Validates ObservationRecord-to-EvidenceItem mapping, SubjectIdentity, SubjectAlias provenance,
verified alias source references, EvidenceRelevanceGate with structured field attribution,
ResearchDimension decomposition with strict DimensionSuitability claim gates,
VideoSubstantiveCoverage vs SourceFamilyPresence separation, and EvidenceBundleSemanticValidator.
"""

from datetime import datetime, timedelta, timezone
import unittest
from tools.evidence.builder import EvidenceBuilder, ProductIsolationViolationError
from tools.evidence.conflicts import ConflictTracker, GapTracker
from tools.evidence.freshness import FreshnessEvaluator
from tools.evidence.grounding import GroundingContextBuilder
from tools.evidence.models import (
    AliasVerificationStatus,
    CollectionProvenance,
    ConflictRelationType,
    ContentRole,
    DimensionCoverageStatus,
    EvidenceBundle,
    EvidenceConflict,
    EvidenceGap,
    EvidenceItem,
    FreshnessPolicy,
    FreshnessPolicySource,
    FreshnessState,
    GroundingContext,
    RejectedEvidenceRecord,
    RelevanceAnchorType,
    RelevanceAssessment,
    RelevanceMatchField,
    RelevanceMatchMethod,
    RelevanceStatus,
    RelevanceTraceItem,
    ResearchCoverageReport,
    ResearchDimension,
    ResearchSourceCoverage,
    SemanticCoherenceStatus,
    SourceFamily,
    SourceRelationship,
    SubjectAlias,
    SubjectAliasType,
    SubjectIdentity,
    VideoSubstantiveCoverage,
)
from tools.evidence.relevance import (
    EvidenceBundleSemanticValidator,
    EvidenceRelevanceGate,
    ResearchDimensionEvaluator,
)
from tools.observation.models import (
    BackendMaturityState,
    ContentTrustLevel,
    ContentTruthStatus,
    ExtractionConfidence,
    ObservationRecord,
    SearchScope,
    SearXNGAdapterState,
    SourceCredibility,
)
from tools.observation.search_backend import (
    DuckDuckGoHtmlSearchBackend,
    SearchManager,
    SearXNGSearchBackend,
    WikipediaSearchBackend,
)


class TestEvidenceIntegration(unittest.TestCase):
    def setUp(self):
        self.product_id = "PROD_DESK_LAMP"
        self.brand_id = "BRAND_LUMEN"
        self.lamp_subject = SubjectIdentity(
            product_id="PROD_DESK_LAMP",
            brand_id="BRAND_LUMEN",
            canonical_name="LumenDesk Pro",
            brand_name="Lumen",
            aliases=[
                SubjectAlias(
                    value="lumendesk",
                    alias_type=SubjectAliasType.CANONICAL,
                    verification_status=AliasVerificationStatus.VERIFIED,
                    verified_by="PROJECT_CONFIGURATION",
                    source_reference="https://lumenlamp.com/about",
                    verified_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                ),
                SubjectAlias(
                    value="lumen-lamp-unverified",
                    alias_type=SubjectAliasType.COMMUNITY_ALIAS,
                    verification_status=AliasVerificationStatus.UNVERIFIED,
                ),
            ],
            official_domains=["lumenlamp.com"],
            official_handles=["@lumenlights"],
            known_product_names=["LumenDesk Pro 1", "LumenDesk Pro 2"],
            known_company_names=["Lumen Tech Inc"],
            category_terms=["lighting", "desk lamp", "LED", "workspace illumination"],
        )
        self.ollama_subject = SubjectIdentity(
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            canonical_name="Ollama",
            brand_name="Ollama",
            aliases=[
                SubjectAlias(
                    value="ollama",
                    alias_type=SubjectAliasType.CANONICAL,
                    verification_status=AliasVerificationStatus.VERIFIED,
                    verified_by="PROJECT_CONFIGURATION",
                    source_reference="https://github.com/ollama/ollama",
                    verified_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                ),
                SubjectAlias(
                    value="@ollama",
                    alias_type=SubjectAliasType.OFFICIAL_HANDLE,
                    verification_status=AliasVerificationStatus.VERIFIED,
                    verified_by="OFFICIAL_REPO_DOCS",
                    source_reference="https://ollama.com",
                    verified_at=datetime(2026, 8, 16, tzinfo=timezone.utc),
                ),
                SubjectAlias(
                    value="ollamarun",
                    alias_type=SubjectAliasType.CANDIDATE_ALIAS,
                    verification_status=AliasVerificationStatus.UNVERIFIED,
                    source_reference="unverified_candidate_mention",
                ),
                SubjectAlias(
                    value="ollama-cli-unverified",
                    alias_type=SubjectAliasType.COMMUNITY_ALIAS,
                    verification_status=AliasVerificationStatus.UNVERIFIED,
                ),
            ],
            official_domains=["ollama.com"],
            official_handles=["@ollama"],
            known_product_names=["Ollama 0.1", "Ollama 0.2", "Ollama 0.3"],
            known_company_names=["Ollama Inc"],
            category_terms=["AI", "LLM", "large language model", "local models", "inference", "quantization", "gguf"],
        )

    # -------------------------------------------------------------
    # 1. ObservationRecord -> EvidenceItem Conversion & Content Roles
    # -------------------------------------------------------------
    def test_observation_to_evidence_item_mapping_and_roles(self):
        """Verify ObservationRecords across different capabilities map to distinct ContentRoles."""
        now = datetime.now(timezone.utc)

        # Search Discovery -> DISCOVERY
        obs_search = ObservationRecord(
            capability="search_web",
            source_platform="search_engine",
            source_type="search_discovery",
            source_url_or_id="search://searxng?q=desk%20lamp",
            backend_used="search_searxng",
            normalized_data={"search_results": {"results": [{"rank": 1, "title": "Best Lamp", "url": "https://lumenlamp.com", "snippet": "A great lamp"}]}},
            product_id=self.product_id,
            brand_id=self.brand_id,
            collected_at=now,
        )
        ev_search = EvidenceBuilder.observation_to_evidence(obs_search)
        self.assertEqual(ev_search.content_role, ContentRole.DISCOVERY)
        self.assertEqual(ev_search.collection_provenance, CollectionProvenance.SELF_HOSTED_META_SEARCH)
        self.assertEqual(ev_search.source_family, SourceFamily.SEARCH_DISCOVERY)
        self.assertTrue(ev_search.evidence_id.startswith("EVID-SRCH-"))

        # Fetched Page -> FETCHED_SOURCE_CONTENT
        obs_page = ObservationRecord(
            capability="read_page",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://lumenlamp.com/review",
            backend_used="http_static",
            normalized_data={"main_text": "Detailed review text of the LumenDesk Pro features.", "title": "Review"},
            product_id=self.product_id,
            brand_id=self.brand_id,
            collected_at=now,
        )
        ev_page = EvidenceBuilder.observation_to_evidence(obs_page, target_subject_domain="lumenlamp.com")
        self.assertEqual(ev_page.content_role, ContentRole.FETCHED_SOURCE_CONTENT)
        self.assertEqual(ev_page.collection_provenance, CollectionProvenance.DIRECT_PUBLISHER_PAGE)
        self.assertEqual(ev_page.source_relationship, SourceRelationship.FIRST_PARTY_TO_SUBJECT)
        self.assertEqual(ev_page.source_family, SourceFamily.FIRST_PARTY_WEB)

        # YouTube Metadata -> PLATFORM_REPORTED_METRIC
        obs_yt = ObservationRecord(
            capability="youtube_metadata",
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://youtube.com/watch?v=12345678901",
            backend_used="youtube_ytdlp",
            normalized_data={"title": "LumenDesk Pro Unboxing", "reported_view_count": 50000},
            product_id=self.product_id,
            brand_id=self.brand_id,
            collected_at=now,
        )
        ev_yt = EvidenceBuilder.observation_to_evidence(obs_yt)
        self.assertEqual(ev_yt.content_role, ContentRole.PLATFORM_REPORTED_METRIC)
        self.assertEqual(ev_yt.source_family, SourceFamily.VIDEO)

    # -------------------------------------------------------------
    # 2. Product Isolation & Freshness Decay (Restored Tests)
    # -------------------------------------------------------------
    def test_product_isolation_blocks_cross_product_evidence(self):
        """Verify EvidenceBundle assembly strictly rejects cross-product items."""
        now = datetime.now(timezone.utc)
        item_correct = EvidenceItem(
            observation_id="OBS-1",
            capability="read_page",
            product_id="PROD_DESK_LAMP",
            brand_id="BRAND_LUMEN",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://lamp.com",
            backend_used="http_static",
            collected_at=now,
        )
        item_foreign = EvidenceItem(
            observation_id="OBS-2",
            capability="read_page",
            product_id="PROD_HEADPHONES",
            brand_id="BRAND_AUDIO",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://audio.com",
            backend_used="http_static",
            collected_at=now,
        )

        with self.assertRaises(ProductIsolationViolationError):
            EvidenceBuilder.assemble_bundle(
                task_id="TASK_001",
                product_id="PROD_DESK_LAMP",
                brand_id="BRAND_LUMEN",
                research_question="Assess lamp feedback",
                evidence_items=[item_correct, item_foreign],
            )

    def test_freshness_decay_evaluation(self):
        """Verify FreshnessEvaluator computes CURRENT, RECENT, STALE based on capability thresholds."""
        now = datetime.now(timezone.utc)
        t_5d = now - timedelta(days=5)
        st_price, days_price, p_src = FreshnessEvaluator.evaluate("pricing", collected_at=now, observed_at=t_5d, now=now)
        self.assertEqual(st_price, FreshnessState.CURRENT)
        self.assertEqual(days_price, 5.0)

        t_45d = now - timedelta(days=45)
        st_price_stale, _, _ = FreshnessEvaluator.evaluate("pricing", collected_at=now, observed_at=t_45d, now=now)
        self.assertEqual(st_price_stale, FreshnessState.STALE)

    def test_conflict_relation_types_and_different_scope(self):
        """Verify conflict tracker cleanly distinguishes CONTRADICTION from DIFFERENT_SCOPE."""
        conf_scope = ConflictTracker.create_conflict(
            topic="Operational Friction",
            evidence_ids=["EVID-3", "EVID-4"],
            relation_type=ConflictRelationType.DIFFERENT_SCOPE,
            claim_a="CLI install is 1 command",
            claim_b="70B model requires 64GB RAM and GPU acceleration",
            shared_dimension="OPERATIONAL_FRICTION",
            condition_a="Basic tool installation",
            condition_b="Heavy inference workload",
        )
        self.assertEqual(conf_scope.relation_type, ConflictRelationType.DIFFERENT_SCOPE)
        self.assertEqual(conf_scope.resolution_status, "UNRESOLVED")

    def test_research_source_family_coverage_audit(self):
        """Verify EvidenceBundle correctly audits research question source family coverage."""
        now = datetime.now(timezone.utc)
        item_first = EvidenceItem(
            observation_id="OBS-1",
            capability="read_page",
            product_id=self.product_id,
            brand_id=self.brand_id,
            source_platform="web",
            source_type="article",
            source_url_or_id="https://lamp.com",
            backend_used="http_static",
            source_family=SourceFamily.FIRST_PARTY_WEB,
            collected_at=now,
        )
        bundle_partial = EvidenceBuilder.assemble_bundle(
            task_id="TASK_COV_01",
            product_id=self.product_id,
            brand_id=self.brand_id,
            research_question="Assess lamp across web and community",
            evidence_items=[item_first],
            requested_source_families=[SourceFamily.FIRST_PARTY_WEB, SourceFamily.COMMUNITY],
        )
        self.assertEqual(bundle_partial.research_source_coverage, ResearchSourceCoverage.PARTIAL)
        self.assertIn(SourceFamily.COMMUNITY, bundle_partial.missing_source_families)

    def test_transaction_gap_preserved_after_video_addition(self):
        """Verify adding video views does NOT close or alter TRANSACTION_DATA gap."""
        now = datetime.now(timezone.utc)
        item_yt = EvidenceItem(
            observation_id="OBS-YT-1",
            capability="youtube_metadata",
            product_id=self.product_id,
            brand_id=self.brand_id,
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://youtube.com/watch?v=1",
            backend_used="youtube_ytdlp",
            content_role=ContentRole.PLATFORM_REPORTED_METRIC,
            source_family=SourceFamily.VIDEO,
            collected_at=now,
        )
        gap = GapTracker.create_gap(
            question="What is the commercial revenue conversion rate?",
            required_evidence_type="TRANSACTION_DATA",
            importance="HIGH",
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_GAP_01",
            product_id=self.product_id,
            brand_id=self.brand_id,
            research_question="Assess lamp market metrics",
            evidence_items=[item_yt],
            evidence_gaps=[gap],
        )
        self.assertEqual(len(bundle.evidence_gaps), 1)
        self.assertEqual(bundle.evidence_gaps[0].status, "MISSING")

    def test_bounded_content_truncation_metadata(self):
        """Verify oversized source bodies are bounded deterministically with truncation metadata."""
        huge_text = "A" * 10000
        obs = ObservationRecord(
            capability="read_page",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://example.com/huge",
            backend_used="http_static",
            normalized_data={"main_text": huge_text},
            product_id=self.product_id,
            brand_id=self.brand_id,
        )
        ev_item = EvidenceBuilder.observation_to_evidence(obs, max_content_chars=500)
        self.assertTrue(ev_item.content_truncated)
        self.assertEqual(ev_item.included_length, 500)

    def test_grounding_context_construction(self):
        """Verify GroundingContext compiles explicit grounding rules and unknown facts."""
        now = datetime.now(timezone.utc)
        item = EvidenceItem(
            observation_id="OBS-1",
            capability="read_page",
            product_id=self.product_id,
            brand_id=self.brand_id,
            source_platform="web",
            source_type="article",
            source_url_or_id="https://lamp.com",
            backend_used="http_static",
            collected_at=now,
        )
        gap = GapTracker.create_gap("Are returns high?", "RETURN_METRICS")
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_RESEARCH_01",
            product_id=self.product_id,
            brand_id=self.brand_id,
            research_question="Assess lamp market feedback",
            evidence_items=[item],
            evidence_gaps=[gap],
        )
        gctx = GroundingContextBuilder.build_grounding_context(
            bundle=bundle,
            task_description="Analyze market reception",
            business_context="Desk lamp launch",
        )
        self.assertEqual(gctx.product_id, self.product_id)
        self.assertEqual(len(gctx.evidence_items), 1)
        self.assertIn("Missing RETURN_METRICS", gctx.unknown_facts[0])

    # -------------------------------------------------------------
    # 3. Subject Relevance Gate & Trace Attribution
    # -------------------------------------------------------------
    def test_relevance_gate_rejects_unrelated_video_me_at_the_zoo(self):
        """Verify 'Me at the zoo' (jNQXAC9IVRw) is deterministically rejected as IRRELEVANT for Ollama."""
        now = datetime.now(timezone.utc)
        obs_zoo = ObservationRecord(
            capability="youtube_metadata",
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            backend_used="youtube_ytdlp",
            normalized_data={
                "title": "Me at the zoo",
                "channel_name": "jawed",
                "description": "The first video on YouTube. Standing in front of elephants.",
                "reported_view_count": 300000000,
            },
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            collected_at=now,
        )
        ev_zoo = EvidenceBuilder.observation_to_evidence(obs_zoo)
        assessment = EvidenceRelevanceGate.evaluate(ev_zoo, self.ollama_subject)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.IRRELEVANT)

    def test_matching_product_id_alone_does_not_establish_relevance(self):
        """Verify labeling an item with PRODUCT_ID does not bypass the Relevance Gate."""
        now = datetime.now(timezone.utc)
        item_mismatch = EvidenceItem(
            observation_id="OBS-MISMATCH",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://recipes.com/best-chocolate-cake",
            bounded_content="How to bake a rich chocolate cake with cocoa powder.",
            backend_used="http_static",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_mismatch, self.ollama_subject)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.IRRELEVANT)

    def test_category_terms_alone_do_not_establish_relevance(self):
        """Verify generic category terms (AI, LLM, local) without canonical anchors evaluate to IRRELEVANT."""
        now = datetime.now(timezone.utc)
        item_generic = EvidenceItem(
            observation_id="OBS-GENERIC",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://tech-news.com/general-ai-trends",
            bounded_content="Overview of AI and LLM inference algorithms and quantization benchmarks across industry.",
            backend_used="http_static",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_generic, self.ollama_subject)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.IRRELEVANT)

    def test_official_domain_establishes_strong_subject_identity(self):
        """Verify matching official_domains establishes RELEVANT status."""
        now = datetime.now(timezone.utc)
        item_official = EvidenceItem(
            observation_id="OBS-OFFICIAL",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://ollama.com/download",
            source_domain="ollama.com",
            bounded_content="Get up and running with Llama 3 and Mistral locally.",
            backend_used="http_static",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_official, self.ollama_subject)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.RELEVANT)

    def test_youtube_title_match_records_field_title_not_url(self):
        """Verify matching on YouTube title records field=title without false url attribution."""
        now = datetime.now(timezone.utc)
        item_yt = EvidenceItem(
            observation_id="OBS-YT-TITLE",
            capability="youtube_metadata",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://www.youtube.com/watch?v=AGAETsxjg0o",
            bounded_content="Title: Learn Ollama in 10 Minutes - Run LLMs Locally for FREE\nChannel: TechDev\nViews: 50000",
            backend_used="youtube_ytdlp",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_yt, self.ollama_subject)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.RELEVANT)
        title_traces = [t for t in assessment.structured_traces if t.field == RelevanceMatchField.TITLE and t.anchor_type == RelevanceAnchorType.CANONICAL_NAME]
        url_traces = [t for t in assessment.structured_traces if t.field == RelevanceMatchField.URL and t.anchor_type == RelevanceAnchorType.CANONICAL_NAME]
        self.assertGreaterEqual(len(title_traces), 1)
        self.assertEqual(len(url_traces), 0)

    def test_url_match_only_occurs_if_url_actually_contains_anchor(self):
        """Verify URL field match occurs ONLY when the URL token explicitly contains the canonical anchor."""
        now = datetime.now(timezone.utc)
        item_url = EvidenceItem(
            observation_id="OBS-URL-HIT",
            capability="search_web",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="search_engine",
            source_type="search_discovery",
            source_url_or_id="search://ddg?q=Ollama%20local%20model",
            bounded_content="Generic snippet text",
            backend_used="search_duckduckgo_html",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_url, self.ollama_subject)
        url_traces = [t for t in assessment.structured_traces if t.field == RelevanceMatchField.URL]
        self.assertGreaterEqual(len(url_traces), 1)
        self.assertEqual(url_traces[0].matched_value.lower(), "ollama")

    # -------------------------------------------------------------
    # 4. Subject Alias Provenance & Verification Tests (Phase 3D.1.4)
    # -------------------------------------------------------------
    def test_unverified_alias_cannot_independently_establish_relevant(self):
        """Verify an UNVERIFIED alias matches with UNVERIFIED status and evaluates to IRRELEVANT if no canonicals exist."""
        now = datetime.now(timezone.utc)
        sub_with_unverified = SubjectIdentity(
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            canonical_name="Ollama",
            brand_name="Ollama",
            aliases=[
                SubjectAlias(
                    value="candidate-runner-alias",
                    alias_type=SubjectAliasType.COMMUNITY_ALIAS,
                    verification_status=AliasVerificationStatus.UNVERIFIED,
                ),
            ],
            official_domains=["ollama.com"],
        )
        item_unverified = EvidenceItem(
            observation_id="OBS-UNVERIFIED",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://random-blog.com/post",
            bounded_content="We discussed the candidate-runner-alias experimental branch in our meeting.",
            backend_used="http_static",
            collected_at=now,
        )
        assessment = EvidenceRelevanceGate.evaluate(item_unverified, sub_with_unverified)
        self.assertEqual(assessment.relevance_status, RelevanceStatus.IRRELEVANT)
        self.assertTrue(any(t.anchor_type == RelevanceAnchorType.UNVERIFIED_ALIAS for t in assessment.structured_traces))

    def test_verified_alias_requires_source_reference(self):
        """Verify SubjectAlias cannot be initialized as VERIFIED without a valid source_reference or PROJECT_CONFIGURATION."""
        alias_invalid = SubjectAlias(
            value="some-alias",
            alias_type=SubjectAliasType.COMMUNITY_ALIAS,
            verification_status=AliasVerificationStatus.VERIFIED,
            source_reference=None,
            verified_by="manual",
        )
        # In __post_init__, missing source_reference causes automatic downgrade to UNVERIFIED
        self.assertEqual(alias_invalid.verification_status, AliasVerificationStatus.UNVERIFIED)

    def test_unsupported_ollamarun_does_not_remain_verified(self):
        """Verify ollamarun is marked UNVERIFIED in the official subject definition."""
        alias_ollamarun = next((a for a in self.ollama_subject.aliases if a.value == "ollamarun"), None)
        self.assertIsNotNone(alias_ollamarun)
        self.assertEqual(alias_ollamarun.verification_status, AliasVerificationStatus.UNVERIFIED)
        self.assertEqual(alias_ollamarun.alias_type, SubjectAliasType.CANDIDATE_ALIAS)

    # -------------------------------------------------------------
    # 5. Dimension Suitability Policy & Exclusions (Phase 3D.1.4)
    # -------------------------------------------------------------
    def test_search_discovery_cannot_substantively_support_market_positioning(self):
        """Verify SEARCH_DISCOVERY items are excluded from substantive MARKET_POSITIONING support."""
        now = datetime.now(timezone.utc)
        item_search = EvidenceItem(
            observation_id="OBS-SRCH-1",
            capability="search_web",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="search_engine",
            source_type="search_discovery",
            source_url_or_id="search://ddg?q=Ollama",
            content_role=ContentRole.DISCOVERY,
            source_family=SourceFamily.SEARCH_DISCOVERY,
            relevance_status=RelevanceStatus.RELEVANT,
            bounded_content="Title: Ollama search results",
            backend_used="search_duckduckgo_html",
            collected_at=now,
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_SUIT_01",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Assess market positioning",
            evidence_items=[item_search],
        )
        rep = ResearchDimensionEvaluator.evaluate_bundle(bundle, bundle.research_question)
        dim_pos = next(d for d in rep.dimensions if d.dimension_id == "MARKET_POSITIONING")
        self.assertIn(item_search.evidence_id, dim_pos.excluded_evidence_ids)
        self.assertIn(item_search.evidence_id, dim_pos.exclusion_reasons)
        self.assertNotIn(item_search.evidence_id, dim_pos.supporting_evidence_ids)

    def test_platform_metrics_cannot_establish_developer_reception(self):
        """Verify PLATFORM_REPORTED_METRIC items (views, likes) are excluded from DEVELOPER_RECEPTION."""
        now = datetime.now(timezone.utc)
        item_yt_metrics = EvidenceItem(
            observation_id="OBS-YT-METRICS",
            capability="youtube_metadata",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://youtube.com/watch?v=AGAETsxjg0o",
            content_role=ContentRole.PLATFORM_REPORTED_METRIC,
            source_family=SourceFamily.VIDEO,
            relevance_status=RelevanceStatus.RELEVANT,
            bounded_content="Title: Learn Ollama in 10 Minutes\nViews: 50000",
            backend_used="youtube_ytdlp",
            collected_at=now,
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_SUIT_02",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Assess developer reception",
            evidence_items=[item_yt_metrics],
        )
        rep = ResearchDimensionEvaluator.evaluate_bundle(bundle, bundle.research_question)
        dim_rec = next(d for d in rep.dimensions if d.dimension_id == "DEVELOPER_RECEPTION")
        self.assertIn(item_yt_metrics.evidence_id, dim_rec.excluded_evidence_ids)
        self.assertIn("engagement observations", dim_rec.exclusion_reasons[item_yt_metrics.evidence_id])

    def test_installation_instructions_not_evidence_of_friction(self):
        """Verify official installation procedure without user difficulty observations is excluded from OPERATIONAL_FRICTION."""
        now = datetime.now(timezone.utc)
        item_official_install = EvidenceItem(
            observation_id="OBS-OFFICIAL-INSTALL",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://ollama.com",
            content_role=ContentRole.FETCHED_SOURCE_CONTENT,
            source_family=SourceFamily.FIRST_PARTY_WEB,
            relevance_status=RelevanceStatus.RELEVANT,
            bounded_content="Title: Ollama\nContent: Run Llama 3 locally. Install: curl -fsSL https://ollama.com/install.sh",
            backend_used="http_static",
            collected_at=now,
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_SUIT_03",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Assess operational friction",
            evidence_items=[item_official_install],
        )
        rep = ResearchDimensionEvaluator.evaluate_bundle(bundle, bundle.research_question)
        dim_fric = next(d for d in rep.dimensions if d.dimension_id == "OPERATIONAL_FRICTION")
        self.assertIn(item_official_install.evidence_id, dim_fric.excluded_evidence_ids)
        self.assertIn("document procedure", dim_fric.exclusion_reasons[item_official_install.evidence_id])

    def test_forum_sample_produces_representativeness_limitation(self):
        """Verify single bounded forum thread produces PARTIAL developer reception with explicit sampling limitation."""
        now = datetime.now(timezone.utc)
        item_hn = EvidenceItem(
            observation_id="OBS-HN",
            capability="read_forum_thread",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="hacker_news",
            source_type="discussion_thread",
            source_url_or_id="https://news.ycombinator.com/item?id=37661755",
            content_role=ContentRole.USER_GENERATED_CONTENT,
            source_family=SourceFamily.COMMUNITY,
            relevance_status=RelevanceStatus.RELEVANT,
            bounded_content="Title: Ollama for Linux\nContent: Great release! Easy to run local models on my workstation.",
            backend_used="discussion_public",
            collected_at=now,
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_SUIT_04",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Assess developer reception",
            evidence_items=[item_hn],
        )
        rep = ResearchDimensionEvaluator.evaluate_bundle(bundle, bundle.research_question)
        dim_rec = next(d for d in rep.dimensions if d.dimension_id == "DEVELOPER_RECEPTION")
        self.assertEqual(dim_rec.coverage_status, DimensionCoverageStatus.PARTIAL)
        self.assertTrue(len(dim_rec.sampling_limitations) > 0)
        self.assertIn("not general population truth", dim_rec.sampling_limitations[0])

    def test_bundle_semantic_validator_quarantines_irrelevant_items(self):
        """Verify EvidenceBundleSemanticValidator excludes irrelevant items from coverage and records rejected manifest."""
        now = datetime.now(timezone.utc)
        item_valid_web = EvidenceItem(
            observation_id="OBS-1",
            capability="read_page",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="web",
            source_type="article",
            source_url_or_id="https://ollama.com",
            source_domain="ollama.com",
            bounded_content="Ollama official downloads and documentation.",
            backend_used="http_static",
            source_family=SourceFamily.FIRST_PARTY_WEB,
            collected_at=now,
        )
        item_zoo = EvidenceItem(
            observation_id="OBS-ZOO",
            capability="youtube_metadata",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            source_platform="youtube",
            source_type="video",
            source_url_or_id="https://www.youtube.com/watch?v=jNQXAC9IVRw",
            bounded_content="Title: Me at the zoo\nDescription: First video on YouTube.",
            backend_used="youtube_ytdlp",
            source_family=SourceFamily.VIDEO,
            collected_at=now,
        )
        bundle = EvidenceBuilder.assemble_bundle(
            task_id="TASK_VAL_01",
            product_id="PROD_OLLAMA_LOCAL_AI",
            brand_id="BRAND_OLLAMA",
            research_question="Assess Ollama across web and video",
            evidence_items=[item_valid_web, item_zoo],
            requested_source_families=[SourceFamily.FIRST_PARTY_WEB, SourceFamily.VIDEO],
        )
        coherence, rejected, notes = EvidenceBundleSemanticValidator.validate(bundle, self.ollama_subject)
        self.assertEqual(coherence, SemanticCoherenceStatus.PARTIAL)
        self.assertEqual(bundle.research_source_coverage, ResearchSourceCoverage.PARTIAL)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].evidence_id, item_zoo.evidence_id)

    # -------------------------------------------------------------
    # 6. Search Backend State & Scope Hardening
    # -------------------------------------------------------------
    def test_search_scope_and_backend_maturity_hardening(self):
        """Verify Wikipedia scope is ENCYCLOPEDIC_REFERENCE and DDG carries EXPERIMENTAL maturity."""
        wiki = WikipediaSearchBackend()
        self.assertEqual(wiki.supported_scope, SearchScope.ENCYCLOPEDIC_REFERENCE)
        self.assertEqual(wiki.maturity_state, BackendMaturityState.READY)

        ddg = DuckDuckGoHtmlSearchBackend()
        self.assertEqual(ddg.maturity_state, BackendMaturityState.EXPERIMENTAL)
        self.assertEqual(ddg.provenance, "UNOFFICIAL_HTML_PARSE")

        searxng = SearXNGSearchBackend()
        self.assertEqual(searxng.adapter_state, SearXNGAdapterState.IMPLEMENTED)


if __name__ == "__main__":
    unittest.main()
