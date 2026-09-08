"""Adversarial authority regression for runtime trusted knowledge scope aliases.

Invariant under test:
A run canonically bound to Business/Project A must never retrieve knowledge that
belongs only to Project B merely because a foreign exact/legacy scope alias is
supplied through ``trusted_knowledge_scope``.

Compatibility metadata may preserve a lookup alias that is derivable from the
same canonical business/project authority, but it must not become an independent
authorization primitive.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from knowledge.models import AuthorityLevel, KnowledgeDocument, SourceType
from knowledge.repository import LocalKnowledgeRepository
from runtime.engine import FiveAgentDepartmentRuntime


BUSINESS_A = "BIZ-AUTH-A"
PROJECT_A = "PROJ-AUTH-A"
PROJECT_B = "PROJ-AUTH-B"
FOREIGN_SCOPE_B = f"PROJECT:{PROJECT_B}"
FOREIGN_SENTINEL = "FOREIGN_PROJECT_B_SECRET_MUST_NOT_ENTER_A_CONTEXT"


class TestRuntimeTrustedKnowledgeScopeAuthorityV1(unittest.TestCase):
    @staticmethod
    def _compile_with_single_document(*, document_scope: str, trusted_scope: str, content: str) -> str:
        # Use the real in-memory KnowledgeRepository implementation so the test
        # exercises exact production scope matching without touching user data.
        with patch.dict(os.environ, {"AI_MARKETING_KNOWLEDGE_EPHEMERAL": "1"}):
            knowledge_repo = LocalKnowledgeRepository()

        knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id=f"KNOW-AUTH-{abs(hash((document_scope, content)))}",
                source_id=f"SRC-AUTH-{abs(hash(document_scope))}",
                title="Trusted knowledge scope authority sentinel",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content=content,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                scope=document_scope,
            )
        )

        model_gateway = MagicMock()
        model_gateway.model_policy = None
        memory_repo = MagicMock()
        memory_repo.list_memories.return_value = []

        runtime = FiveAgentDepartmentRuntime(
            model_gateway=model_gateway,
            knowledge_repo=knowledge_repo,
            memory_repo=memory_repo,
        )
        context = runtime.start_run(
            objective="Compile knowledge for Project A authority isolation",
            business_id=BUSINESS_A,
            project_id=PROJECT_A,
            trusted_knowledge_scope=trusted_scope,
        )

        # Production read path: start_run authority -> scope bridge ->
        # ContextCompiler -> KnowledgeRepository.list_documents(scope=...).
        grounded = runtime.context_compiler.compile_grounded_package("cmo", context)
        return "\n".join(item.content for item in grounded.evidence_items)

    def test_foreign_trusted_scope_cannot_widen_project_a_knowledge_authority(self) -> None:
        model_visible_content = self._compile_with_single_document(
            document_scope=FOREIGN_SCOPE_B,
            trusted_scope=FOREIGN_SCOPE_B,
            content=FOREIGN_SENTINEL,
        )
        self.assertNotIn(
            FOREIGN_SENTINEL,
            model_visible_content,
            "STILL PRESENT: caller-bound trusted_knowledge_scope widened Project A authority and exposed Project B knowledge.",
        )

    def test_foreign_opaque_legacy_alias_cannot_become_authority(self) -> None:
        alias = "LEGACY-PROJECT-B-OPAQUE-ALIAS"
        sentinel = "FOREIGN_OPAQUE_ALIAS_SECRET_MUST_NOT_ENTER_A_CONTEXT"
        model_visible_content = self._compile_with_single_document(
            document_scope=alias,
            trusted_scope=alias,
            content=sentinel,
        )
        self.assertNotIn(sentinel, model_visible_content)

    def test_same_project_legacy_alias_remains_compatible(self) -> None:
        alias = f"SCOPE_PROJ_{PROJECT_A}"
        sentinel = "AUTHORIZED_PROJECT_A_LEGACY_ALIAS_CONTENT"
        model_visible_content = self._compile_with_single_document(
            document_scope=alias,
            trusted_scope=alias,
            content=sentinel,
        )
        self.assertIn(sentinel, model_visible_content)

    def test_same_business_legacy_alias_remains_compatible(self) -> None:
        alias = f"SCOPE_{BUSINESS_A}"
        sentinel = "AUTHORIZED_BUSINESS_A_LEGACY_ALIAS_CONTENT"
        model_visible_content = self._compile_with_single_document(
            document_scope=alias,
            trusted_scope=alias,
            content=sentinel,
        )
        self.assertIn(sentinel, model_visible_content)


if __name__ == "__main__":
    unittest.main()
