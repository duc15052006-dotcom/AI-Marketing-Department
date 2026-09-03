"""Adversarial regression for natural-language KnowledgeContextBuilder retrieval."""

from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from runtime.knowledge_builder import KnowledgeContextBuilder


class _StaticKnowledgeRepository:
    def __init__(self, documents):
        self._documents = list(documents)

    def list_documents(self, scope=None):
        return [doc for doc in self._documents if doc.scope == scope]


class TestKnowledgeBuilderNaturalLanguageRetrievalAdversarialV1(unittest.TestCase):
    SCOPE = "SCOPE_BIZ_A"

    @classmethod
    def _doc(cls, knowledge_id, authority, title, content, tags=None):
        return KnowledgeDocument(
            knowledge_id=knowledge_id,
            source_id=f"SRC-{knowledge_id}",
            title=title,
            content=content,
            tags=list(tags or []),
            scope=cls.SCOPE,
            freshness="ACTIVE",
            authority_level=authority,
            source_type=SourceType.PRODUCT_GROUND_TRUTH,
        )

    def test_natural_language_query_retrieves_relevant_tier2_instead_of_authority_fallback(self):
        unrelated_tier1 = [
            self._doc(
                f"KNOW-IRRELEVANT-TIER1-{index}",
                AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                f"Brand typography policy {index}",
                "Approved logo spacing, print colors, and visual identity rules.",
            )
            for index in range(4)
        ]
        relevant_id = "KNOW-RELEVANT-TIER2-CHARGER"
        relevant = self._doc(
            relevant_id,
            AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
            "USB-C charger purchase objections",
            "Customers hesitate when a 60W charger runs hot and when warranty coverage is unclear.",
            tags=["charger", "warranty", "heat"],
        )
        builder = KnowledgeContextBuilder(_StaticKnowledgeRepository(unrelated_tier1 + [relevant]))

        result = builder.build_context_for_agent(
            "cmo",
            query_text="Which warranty and heat concerns make customers hesitate when choosing a 60W USB-C charger?",
            scope=self.SCOPE,
        )
        ids = [doc.knowledge_id for doc in result.documents]

        self.assertIn(
            relevant_id,
            ids,
            "Natural-language token relevance fell through to authority-only fallback and lost the relevant document.",
        )
        self.assertNotEqual(
            ids,
            [doc.knowledge_id for doc in unrelated_tier1],
            "Four unrelated Tier 1 documents consumed the result after a natural-language query.",
        )

    def test_equal_lexical_relevance_keeps_authority_as_tie_break(self):
        tier2 = self._doc(
            "KNOW-TIER2-WARRANTY-HEAT",
            AuthorityLevel.TIER_2_VERIFIED_RESEARCH,
            "Warranty heat evidence",
            "Verified research evidence.",
        )
        tier1 = self._doc(
            "KNOW-TIER1-WARRANTY-HEAT",
            AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            "Warranty heat policy",
            "Canonical product policy.",
        )
        builder = KnowledgeContextBuilder(_StaticKnowledgeRepository([tier2, tier1]))

        result = builder.build_context_for_agent(
            "cmo",
            query_text="Compare warranty heat concerns",
            scope=self.SCOPE,
        )

        self.assertEqual(
            [doc.knowledge_id for doc in result.documents],
            [tier1.knowledge_id, tier2.knowledge_id],
            "Equal lexical relevance must retain authority-first deterministic ordering.",
        )


if __name__ == "__main__":
    unittest.main()
