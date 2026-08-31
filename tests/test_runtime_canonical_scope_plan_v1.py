from __future__ import annotations

import unittest

from runtime.context import RuntimeContext
from runtime.scope_bridge import build_runtime_canonical_scope_plan


class RuntimeCanonicalScopePlanV1Tests(unittest.TestCase):
    def test_project_then_business_then_global_fallback_is_planned_without_combining_tenants(self) -> None:
        context = RuntimeContext(
            objective="Plan a scoped campaign.",
            business_id="BIZ_ALPHA",
            project_id="PROJ_ALPHA",
            campaign_id="CAMP_ALPHA",
        )

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(
            plan.knowledge_scope_keys,
            ("PROJECT:PROJ_ALPHA", "BUSINESS:BIZ_ALPHA"),
        )
        self.assertEqual(
            plan.memory_scope_keys,
            ("PROJECT:PROJ_ALPHA", "BUSINESS:BIZ_ALPHA"),
        )
        self.assertTrue(plan.include_global)
        self.assertNotIn("PROJECT:PROJ_BETA", plan.knowledge_scope_keys)
        self.assertNotIn("PROJECT:PROJ_BETA", plan.memory_scope_keys)

    def test_business_only_context_produces_exact_business_scope(self) -> None:
        context = RuntimeContext(
            objective="Business scoped run.",
            business_id="BIZ_ONLY",
            campaign_id="CAMP_DEFAULT",
        )

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(plan.knowledge_scope_keys, ("BUSINESS:BIZ_ONLY",))
        self.assertEqual(plan.memory_scope_keys, ("BUSINESS:BIZ_ONLY",))
        self.assertTrue(plan.include_global)

    def test_default_business_is_global_fallback_not_private_exact_scope(self) -> None:
        context = RuntimeContext(
            objective="Default workspace run.",
            business_id="BIZ_DEFAULT",
            campaign_id="CAMP_DEFAULT",
        )

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(plan.knowledge_scope_keys, ())
        self.assertEqual(plan.memory_scope_keys, ())
        self.assertTrue(plan.include_global)

    def test_project_scope_survives_default_business_without_becoming_combined_scope(self) -> None:
        context = RuntimeContext(
            objective="Project-only workspace run.",
            business_id="BIZ_DEFAULT",
            project_id="PROJ_LOCAL",
            campaign_id="CAMP_DEFAULT",
        )

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(plan.knowledge_scope_keys, ("PROJECT:PROJ_LOCAL",))
        self.assertEqual(plan.memory_scope_keys, ("PROJECT:PROJ_LOCAL",))
        self.assertNotIn("BUSINESS:BIZ_DEFAULT|PROJECT:PROJ_LOCAL", plan.knowledge_scope_keys)

    def test_mutable_working_state_scope_hints_cannot_spoof_plan(self) -> None:
        context = RuntimeContext(
            objective="Ignore mutable scope hints.",
            business_id="BIZ_TRUSTED",
            project_id="PROJ_TRUSTED",
        )
        context.working_state["knowledge_scope"] = "PROJECT:PROJ_EVIL"
        context.working_state["memory_scope"] = "BUSINESS:BIZ_EVIL"

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(
            plan.knowledge_scope_keys,
            ("PROJECT:PROJ_TRUSTED", "BUSINESS:BIZ_TRUSTED"),
        )
        self.assertEqual(
            plan.memory_scope_keys,
            ("PROJECT:PROJ_TRUSTED", "BUSINESS:BIZ_TRUSTED"),
        )
        self.assertNotIn("EVIL", "|".join(plan.knowledge_scope_keys + plan.memory_scope_keys))

    def test_invalid_authoritative_scope_identifier_fails_closed(self) -> None:
        context = RuntimeContext(
            objective="Reject malformed tenant scope.",
            business_id="BIZ_A|BUSINESS:BIZ_B",
        )

        with self.assertRaises(ValueError):
            build_runtime_canonical_scope_plan(context)

    def test_campaign_is_recorded_but_not_invented_as_retrieval_scope_in_v1(self) -> None:
        context = RuntimeContext(
            objective="Campaign scope is deferred until write-side binding exists.",
            business_id="BIZ_ALPHA",
            project_id="PROJ_ALPHA",
            campaign_id="CAMP_SPECIAL",
        )

        plan = build_runtime_canonical_scope_plan(context)

        self.assertEqual(plan.campaign_id, "CAMP_SPECIAL")
        self.assertTrue(all("CAMPAIGN:" not in key for key in plan.knowledge_scope_keys))
        self.assertTrue(all("CAMPAIGN:" not in key for key in plan.memory_scope_keys))


if __name__ == "__main__":
    unittest.main()
