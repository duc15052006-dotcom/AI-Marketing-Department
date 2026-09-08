"""Adversarial authority regression for runtime trusted knowledge scope aliases.

Invariant under test:
A run canonically bound to Business/Project A must never retrieve knowledge that
belongs only to Project B merely because a foreign exact/legacy scope alias is
supplied through ``trusted_knowledge_scope``.

This file is intentionally RED-first.  Do not weaken the assertion to preserve
legacy alias behavior: compatibility metadata may narrow lookup, but it must not
become an authorization primitive.
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
    def test_foreign_trusted_scope_cannot_widen_project_a_knowledge_authority(self) -> None:
        # Use the real in-memory KnowledgeRepository implementation so the test
        # exercises exact production scope matching without touching user data.
        with patch.dict(os.environ, {"AI_MARKETING_KNOWLEDGE_EPHEMERAL": "1"}):
            knowledge_repo = LocalKnowledgeRepository()

        knowledge_repo.save_document(
            KnowledgeDocument(
                knowledge_id="KNOW-AUTH-FOREIGN-B",
                source_id="SRC-AUTH-FOREIGN-B",
                title="Foreign Project B authority sentinel",
                source_type=SourceType.PRODUCT_GROUND_TRUTH,
                content=FOREIGN_SENTINEL,
                authority_level=AuthorityLevel.TIER_1_CANONICAL_GROUND_TRUTH,
                scope=FOREIGN_SCOPE_B,
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
            trusted_knowledge_scope=FOREIGN_SCOPE_B,
        )

        # Production read path: start_run authority -> scope bridge ->
        # ContextCompiler -> KnowledgeRepository.list_documents(scope=...).
        grounded = runtime.context_compiler.compile_grounded_package("cmo", context)
        model_visible_content = "\n".join(item.content for item in grounded.evidence_items)

        self.assertNotIn(
            FOREIGN_SENTINEL,
            model_visible_content,
            "STILL PRESENT: caller-bound trusted_knowledge_scope widened Project A authority and exposed Project B knowledge.",
        )


if __name__ == "__main__":
    unittest.main()
