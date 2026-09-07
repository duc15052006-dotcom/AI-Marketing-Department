"""Adversarial RED regressions for KnowledgeRepository minimum authority.

Invariant: `query_knowledge(..., min_authority=...)` must fail closed against
knowledge below the requested authority threshold while preserving scope and
query filtering behavior.
"""

from __future__ import annotations

import unittest

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository


class KnowledgeMinAuthorityEnforcementV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = LocalKnowledgeRepository()
        self._save("KNOW-T1", AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH)
        self._save("KNOW-T2", AuthorityLevel.TIER_2_VERIFIED_RESEARCH)
        self._save("KNOW-T3", AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA)
        self._save("KNOW-T4", AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION)
        self._save(
            "KNOW-T1-OTHER-SCOPE",
            AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
            scope="SCOPE_OTHER",
        )

    def _save(
        self,
        knowledge_id: str,
        authority_level: AuthorityLevel,
        *,
        scope: str = "GLOBAL",
    ) -> None:
        self.repo.save_document(
            KnowledgeDocument(
                knowledge_id=knowledge_id,
                source_id=f"SRC-{knowledge_id}",
                title=f"Needle authority document {knowledge_id}",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content=f"needle trusted content for {knowledge_id}",
                authority_level=authority_level,
                scope=scope,
            )
        )

    def _ids(self, *, minimum: AuthorityLevel | None, scope: str = "GLOBAL") -> set[str]:
        return {
            doc.knowledge_id
            for doc in self.repo.query_knowledge(
                "needle",
                scope=scope,
                min_authority=minimum,
            )
        }

    def test_tier_1_minimum_returns_only_canonical_ground_truth(self):
        self.assertEqual(
            self._ids(minimum=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH),
            {"KNOW-T1"},
        )

    def test_tier_2_minimum_excludes_tier_3_and_tier_4(self):
        self.assertEqual(
            self._ids(minimum=AuthorityLevel.TIER_2_VERIFIED_RESEARCH),
            {"KNOW-T1", "KNOW-T2"},
        )

    def test_tier_3_minimum_excludes_only_unverified_tier_4(self):
        self.assertEqual(
            self._ids(minimum=AuthorityLevel.TIER_3_SECONDARY_INDUSTRY_DATA),
            {"KNOW-T1", "KNOW-T2", "KNOW-T3"},
        )

    def test_tier_4_minimum_allows_all_authority_levels_control(self):
        self.assertEqual(
            self._ids(minimum=AuthorityLevel.TIER_4_UNVERIFIED_OBSERVATION),
            {"KNOW-T1", "KNOW-T2", "KNOW-T3", "KNOW-T4"},
        )

    def test_none_minimum_preserves_existing_query_behavior_control(self):
        self.assertEqual(
            self._ids(minimum=None),
            {"KNOW-T1", "KNOW-T2", "KNOW-T3", "KNOW-T4"},
        )

    def test_scope_filter_remains_enforced_with_minimum_authority_control(self):
        self.assertEqual(
            self._ids(
                minimum=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                scope="SCOPE_OTHER",
            ),
            {"KNOW-T1-OTHER-SCOPE"},
        )


if __name__ == "__main__":
    unittest.main()
