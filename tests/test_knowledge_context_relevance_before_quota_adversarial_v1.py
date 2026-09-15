"""Adversarial regression for relevance-aware bounded persistent knowledge selection."""

from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from memory.repository import LocalMemoryRepository
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.knowledge_builder import KnowledgeContextBuilder
from tools.capabilities import CapabilityRegistry
from tools.tool_gateway import ToolGateway


class KnowledgeContextRelevanceBeforeQuotaAdversarialV1Tests(unittest.TestCase):
    SCOPE = "SCOPE_BIZ_A"

    def setUp(self) -> None:
        self.knowledge_repo = LocalKnowledgeRepository()
        self.runtime = FiveAgentDepartmentRuntime(
            knowledge_repo=self.knowledge_repo,
            memory_repo=LocalMemoryRepository(),
            tool_gateway=ToolGateway(capability_registry=CapabilityRegistry()),
        )

    def _save_doc(
        self,
        knowledge_id: str,
        authority: AuthorityLevel,
        *,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> None:
        self.knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=title,
                content=content,
                tags=list(tags or []),
                scope=self.SCOPE,
                freshness="ACTIVE",
                authority_level=authority,
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
            )
        )

    @staticmethod
    def _knowledge_ids(package) -> list[str]:
        return [
            str(item.metadata.get("knowledge_id"))
            for item in package.evidence_items
            if isinstance(item.metadata, dict) and item.metadata.get("knowledge_id")
        ]

    def test_relevant_tier2_is_not_crowded_out_by_four_irrelevant_tier1_documents(self) -> None:
        irrelevant_ids = []
        for index in range(4):
            knowledge_id = f"KNOW-IRRELEVANT-TIER1-{index}"
            irrelevant_ids.append(knowledge_id)
            self._save_doc(
                knowledge_id,
                AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                title="Office brand typography specification",
                content="Canonical logo spacing, font family, print margin, and stationery layout rules.",
                tags=["branding", "typography", "stationery"],
            )

        relevant_id = "KNOW-RELEVANT-TIER2-CHARGER"
        self._save_doc(
            relevant_id,
            AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
            title="USB C charger cable failure research",
            content="Verified customer research on USB C charger cable failure rate, overheating complaints, and return reasons.",
            tags=["usb c", "charger", "cable", "failure", "complaints"],
        )

        ctx = self.runtime.start_run(
            objective="Analyze USB C charger cable failure complaints and return reasons",
            business_id="BIZ_A",
        )
        grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        grounded_ids = self._knowledge_ids(grounded)

        self.assertEqual(4, len(grounded_ids))
        self.assertIn(
            relevant_id,
            grounded_ids,
            "Relevant Tier 2 knowledge was crowded out by four zero-relevance Tier 1 documents before the model boundary.",
        )
        self.assertLess(
            len(set(irrelevant_ids).intersection(grounded_ids)),
            4,
            "All four irrelevant Tier 1 documents consumed the per-scope quota ahead of relevant evidence.",
        )

    def test_natural_language_builder_query_does_not_fall_back_to_irrelevant_authority_only(self) -> None:
        for index in range(4):
            self._save_doc(
                f"KNOW-BUILDER-IRRELEVANT-TIER1-{index}",
                AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                title="Office brand typography specification",
                content="Canonical logo spacing, font family, print margin, and stationery layout rules.",
                tags=["branding", "typography", "stationery"],
            )

        relevant_id = "KNOW-BUILDER-RELEVANT-TIER2-CHARGER"
        self._save_doc(
            relevant_id,
            AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
            title="USB C charger cable failure research",
            content="Verified customer research on USB C charger cable failure rate, overheating complaints, and return reasons.",
            tags=["usb c", "charger", "cable", "failure", "complaints", "returns"],
        )

        result = KnowledgeContextBuilder(self.knowledge_repo).build_context_for_agent(
            "cmo",
            query_text="Please analyze why customers complain about USB C charger cable failures and returns",
            scope=self.SCOPE,
        )
        retrieved_ids = [doc.knowledge_id for doc in result.documents]

        self.assertIn(
            relevant_id,
            retrieved_ids,
            "Natural-language retrieval must use meaningful query terms before bounded authority fallback; the relevant document was dropped.",
        )
        self.assertLess(
            sum(knowledge_id.startswith("KNOW-BUILDER-IRRELEVANT-TIER1-") for knowledge_id in retrieved_ids),
            4,
            "All four irrelevant high-authority documents consumed the builder quota after the full query sentence failed exact substring matching.",
        )

    def test_budget_truncation_does_not_claim_unrendered_knowledge(self) -> None:
        query = "exact budget probe"
        for index in range(2):
            self._save_doc(
                f"KNOW-BUDGET-PROBE-{index}",
                AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                title=f"{query} document {index}",
                content=f"{query} content {index} with enough text to exceed a one-character budget.",
                tags=[query],
            )

        result = KnowledgeContextBuilder(self.knowledge_repo).build_context_for_agent(
            "cmo",
            query_text=query,
            scope=self.SCOPE,
            max_chars=1,
        )

        self.assertIn("Knowledge context truncated", result.context_text)
        self.assertNotIn("[KNOWLEDGE REF:", result.context_text)
        self.assertEqual(
            [],
            result.documents,
            "Documents excluded by the render budget must not remain in the result provenance envelope.",
        )
        self.assertEqual(
            [],
            result.citations,
            "A citation must not be emitted for a document that never crossed the context budget boundary.",
        )
        self.assertEqual(
            0,
            result.retrieved_count,
            "retrieved_count must account for documents actually rendered into the returned context.",
        )

    def test_equal_relevance_still_prefers_higher_authority_before_quota(self) -> None:
        common_title = "USB C charger cable safety evidence"
        common_content = "USB C charger cable safety failure complaints return reasons."
        common_tags = ["usb c", "charger", "cable", "safety", "failure", "complaints"]

        tier2_ids = []
        for index in range(4):
            knowledge_id = f"KNOW-EQUAL-TIER2-{index}"
            tier2_ids.append(knowledge_id)
            self._save_doc(
                knowledge_id,
                AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
                title=common_title,
                content=common_content,
                tags=common_tags,
            )

        tier1_id = "KNOW-EQUAL-TIER1-CANONICAL"
        self._save_doc(
            tier1_id,
            AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            title=common_title,
            content=common_content,
            tags=common_tags,
        )

        ctx = self.runtime.start_run(
            objective="Review USB C charger cable safety failure complaints and return reasons",
            business_id="BIZ_A",
        )
        grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        grounded_ids = self._knowledge_ids(grounded)

        self.assertEqual(4, len(grounded_ids))
        self.assertIn(
            tier1_id,
            grounded_ids,
            "Equal-relevance Tier 1 canonical evidence must still outrank Tier 2 before bounded selection.",
        )
        self.assertLess(
            len(set(tier2_ids).intersection(grounded_ids)),
            4,
            "All Tier 2 rows occupied the quota despite an equally relevant Tier 1 canonical document.",
        )

    def test_opaque_machine_identifier_cannot_commandeer_semantic_relevance_quota(self) -> None:
        stable_ids = []
        for index in range(4):
            knowledge_id = f"KNOW-STABLE-TIER1-{index}"
            stable_ids.append(knowledge_id)
            self._save_doc(
                knowledge_id,
                AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                title=f"ordinary canonical document {index}",
                content=f"ordinary canonical content {index}",
            )

        opaque_probe = "PROVENANCE_GROUNDED_BOUNDARY_60"
        opaque_id = "KNOW-OPAQUE-ID-MATCH"
        self._save_doc(
            opaque_id,
            AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            title=f"exact query match {opaque_probe}",
            content=f"exact query match {opaque_probe}",
        )

        ctx = self.runtime.start_run(objective=opaque_probe, business_id="BIZ_A")
        grounded = self.runtime.context_compiler.compile_grounded_package("cmo", ctx)
        grounded_ids = self._knowledge_ids(grounded)

        self.assertEqual(stable_ids, grounded_ids)
        self.assertNotIn(
            opaque_id,
            grounded_ids,
            "Opaque machine identifiers must not be treated as semantic relevance signals that reorder the bounded knowledge quota.",
        )


if __name__ == "__main__":
    unittest.main()
