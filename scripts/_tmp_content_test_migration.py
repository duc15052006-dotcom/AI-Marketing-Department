"""One-shot canonical Content test migration for PR #346.

This script updates stale test expectations only. Historical STRATEGIST inputs remain
covered by dedicated compatibility tests and production normalization.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


CANONICAL_TEST_FILES = [
    "tests/test_collaboration_adversarial_final.py",
    "tests/test_collaboration_integrity_audit.py",
    "tests/test_structured_epistemic_handoff.py",
    "tests/test_prod_runtime_01_single_run_authority.py",
    "tests/test_phase5_2_runtime_integration.py",
    "tests/test_prod_core_authority_01a.py",
    "tests/test_phase5_1_foundation.py",
    "tests/test_phase6_1_v1_connectors_and_workspace.py",
    "tests/test_phase1a_runtime_integrity.py",
    "tests/test_prod_core_authority_01b.py",
    "tests/test_claim_evidence_binding.py",
    "tests/test_conversation_router_and_gpt_mode.py",
    "tests/test_material_factual_claim_coverage.py",
    "tests/test_model_execution_bridge.py",
    "tests/test_phase4_3c_15_rc3_architecture.py",
    "tests/test_phase6_2_pilot_and_v1_release.py",
    "tests/test_prod_workflow_failure_semantics_01.py",
    "tests/test_runtime_agent_dna_wiring_28.py",
]

ROLE_REPLACEMENTS = (
    ("execute_stage_strategist", "execute_stage_content"),
    ("RuntimeStage.STRATEGIST", "RuntimeStage.CONTENT"),
    ("BrainAgentId.STRATEGIST", "BrainAgentId.CONTENT"),
    ("AgentId.STRATEGIST", "AgentId.CONTENT"),
    ('"strategist"', '"content"'),
    ("'strategist'", "'content'"),
    ('"STRATEGIST"', '"CONTENT"'),
    ("'STRATEGIST'", "'CONTENT'"),
    ("Strategist", "Content"),
)


def replace_in_file(path: Path, replacements) -> bool:
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")
        return True
    return False


def main() -> None:
    changed: set[str] = set()

    for rel in CANONICAL_TEST_FILES:
        p = Path(rel)
        if replace_in_file(p, ROLE_REPLACEMENTS):
            changed.add(rel)

    # Provider compatibility input stays legacy, canonical output changes to CONTENT.
    p = Path("tests/test_prod_model_gateway_01_provider_registry.py")
    text = p.read_text(encoding="utf-8")
    old = 'self.assertEqual(normalize_agent_id("strategist"), "STRATEGIST")'
    new = 'self.assertEqual(normalize_agent_id("strategist"), "CONTENT")'
    if old in text:
        p.write_text(text.replace(old, new), encoding="utf-8")
        changed.add(str(p))
    elif new not in text:
        raise RuntimeError("provider legacy-normalization assertion changed unexpectedly")

    # Canonical Content stage output schema supersedes the old Strategist positioning schema.
    semantic_replacements = {
        "tests/test_phase1a_runtime_integrity.py": (
            ('strat_out["positioning"]', 'strat_out["content_strategy"]'),
        ),
        "tests/test_collaboration_integrity_audit.py": (
            ('["positioning"]', '["content_strategy"]'),
            ('["field_origins"]["positioning"]', '["field_origins"]["content_strategy"]'),
            ('plan["strategy"]["value_propositions"]', 'plan["content"]["value_propositions"]'),
            ('plan["strategy"]["field_origins"]["content_strategy"]', 'plan["content"]["field_origins"]["content_strategy"]'),
        ),
    }
    for rel, reps in semantic_replacements.items():
        if replace_in_file(Path(rel), reps):
            changed.add(rel)

    # Runtime DNA wiring now targets canonical Content and its authoritative DNA marker.
    p = Path("tests/test_runtime_agent_dna_wiring_28.py")
    if replace_in_file(
        p,
        ((
            '"content": "Marketing Strategy & Growth Architect"',
            '"content": "Content Strategy, Copywriting & Distribution"',
        ),),
    ):
        changed.add(str(p))

    # Canonical CMO role boundaries delegate content semantics to Content and media to Creative.
    p = Path("tests/test_cmo_definition.py")
    if replace_in_file(
        p,
        (
            ('"the primary copywriter"', '"the primary content strategist or copywriter"'),
            ('"the primary video creator"', '"the primary media producer"'),
            ('"STRATEGIST"', '"CONTENT"'),
        ),
    ):
        changed.add(str(p))

    # Intelligence delegates messaging/copy to Content while legacy aliases are tested elsewhere.
    p = Path("tests/test_intelligence_definition.py")
    if replace_in_file(
        p,
        (
            ('"primary copywriter"', '"primary content strategist, copywriter, or scriptwriter"'),
            ('"To STRATEGIST"', '"To CONTENT"'),
        ),
    ):
        changed.add(str(p))

    # Performance sends messaging feedback to canonical Content; CMO owns final strategy.
    p = Path("tests/test_performance_definition.py")
    if replace_in_file(
        p,
        (
            ('"final business strategist"', '"strategy or positioning owner"'),
            ('"PERFORMANCE-TO-STRATEGIST FEEDBACK"', '"PERFORMANCE-TO-CONTENT FEEDBACK"'),
        ),
    ):
        changed.add(str(p))

    # Creative no longer owns substantive copy/hooks/story copy; validate production authority instead.
    p = Path("tests/test_creative_definition.py")
    if replace_in_file(
        p,
        (
            ('"Creative Director, Copywriter, Scriptwriter, Visual Director & Creative Production Orchestrator"',
             '"Creative Director, Visual Director & Creative Production Orchestrator"'),
            ('"transform validated market intelligence and strategic positioning into original"',
             '"transform CMO-approved strategy/positioning and Content-approved messaging"'),
            ('"final business strategist"', '"strategy or positioning owner"'),
            ('"ad network publisher"', '"live publisher or deployment authority"'),
            ('"Creative Territories & Angle Generation"', '"Visual Creative Territories & Treatment Generation"'),
            ('"Hook Engineering & Hook-Promise Consistency"', '"Visual Hook Execution & Hook-Promise Fidelity"'),
            ('"Hook Archetypes"', '"Visual Opening Treatments"'),
            ('"The Hook-Promise Consistency Mandate"', '"Hook-Promise Fidelity Mandate"'),
            ('"Clickbait that fails to deliver damages brand trust"', '"must not overstate, contradict, or silently rewrite"'),
            ('"Copywriting & Anti-Generic-AI Writing Standard"', '"Copy Fidelity & On-Asset Text QA"'),
            ('"Clarity over Cleverness"', '"Message Fidelity"'),
            ('"Anti-Generic-AI Writing Protocol"', '"Creative Text QA"'),
            ('"Formulaic Openings"', '"Content owns substantive copy"'),
            ('"Generic Superlatives"', '"Revision Handoff"'),
            ('"Storytelling (Non-Dogmatic & Context-Appropriate)"', '"Visual Storytelling & Narrative Production"'),
        ),
    ):
        changed.add(str(p))

    # Frozen hashes remain guards, but migrate the explicitly changed canonical DNA bytes once.
    current_hashes = {
        "performance": hashlib.sha256(Path(".agents/agents/performance/agent.md").read_bytes()).hexdigest(),
        "cmo": hashlib.sha256(Path(".agents/agents/cmo/agent.md").read_bytes()).hexdigest(),
    }
    old_hashes = {
        "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9": current_hashes["performance"],
        "766edaf82a8493b82e42d6e61fdca615bc4bfa678ce419f43aee0ae7e86bd52e": current_hashes["cmo"],
    }
    for p in Path("tests").glob("test_*.py"):
        if replace_in_file(p, tuple(old_hashes.items())):
            changed.add(str(p))

    # Retire obsolete permanent Strategist DNA test and replace it with canonical Content coverage.
    obsolete = Path("tests/test_strategist_definition.py")
    if obsolete.exists():
        obsolete.unlink()
        changed.add(str(obsolete))

    content_test = Path("tests/test_content_definition.py")
    content_test.write_text(
        '''"""Canonical Content ASI definition and authority-boundary regressions."""\n\nimport unittest\nfrom pathlib import Path\n\nfrom tests.test_agent_manifests import parse_yaml_frontmatter\n\n\nclass TestContentDefinition(unittest.TestCase):\n    def setUp(self):\n        self.path = Path(__file__).resolve().parent.parent / ".agents" / "agents" / "content" / "agent.md"\n        self.assertTrue(self.path.exists(), "content/agent.md does not exist")\n        self.content = self.path.read_text(encoding="utf-8")\n        self.frontmatter = parse_yaml_frontmatter(self.content)\n\n    def test_content_frontmatter_valid(self):\n        self.assertEqual(self.frontmatter.get("name"), "content")\n        self.assertIn("Content Strategy", self.frontmatter.get("description", ""))\n\n    def test_identity_and_role_boundaries(self):\n        self.assertIn("Content ASI", self.content)\n        self.assertIn("semantic layer between strategy and creative production", self.content)\n        for boundary in ("**not** the CMO", "**not** Intelligence", "**not** Creative", "**not** Performance"):\n            self.assertIn(boundary, self.content)\n\n    def test_canonical_authority_model(self):\n        for capability in (\n            "CONTENT_STRATEGY", "MESSAGE_ARCHITECTURE", "COPY_AND_SCRIPT",\n            "EDITORIAL_PLANNING", "SEO_CONTENT_BRIEFING", "CHANNEL_CONTENT_ADAPTATION",\n            "CONTENT_EXPERIMENT_HYPOTHESES",\n        ):\n            self.assertIn(capability, self.content)\n\n    def test_content_cannot_self_grant_execution_authority(self):\n        for forbidden in (\n            "final commercial sign-off", "live publishing authority", "raw budget mutation",\n            "credential or provider mutation", "direct Body/runtime/tool execution authority",\n        ):\n            self.assertIn(forbidden, self.content)\n\n    def test_epistemic_discipline_has_four_states(self):\n        for state in ("OBSERVED / VERIFIED", "INFERRED", "HYPOTHESIS", "UNKNOWN"):\n            self.assertIn(state, self.content)\n        self.assertIn("Never turn an inference into a fact", self.content)\n\n    def test_required_input_audit(self):\n        for field in (\n            "BUSINESS_OBJECTIVE", "TARGET_AUDIENCE / JTBD", "FUNNEL_STAGE",\n            "CMO_APPROVED_STRATEGY", "PRODUCT_FACTS / PRODUCT_LIMITATIONS",\n            "VERIFIED_CUSTOMER_EVIDENCE",\n        ):\n            self.assertIn(field, self.content)\n\n    def test_message_architecture_is_evidence_grounded(self):\n        for element in (\n            "Audience context", "Problem / desired progress", "Value proposition",\n            "Reason to believe", "Objection handling", "CTA",\n        ):\n            self.assertIn(element, self.content)\n        self.assertIn("preserve lineage", self.content)\n\n    def test_copywriting_frameworks_are_tools_not_dogma(self):\n        for framework in ("AIDA", "PAS", "BAB", "Hook–Value–Proof–CTA", "Claim–Evidence–Implication"):\n            self.assertIn(framework, self.content)\n        self.assertIn("clarity first", self.content)\n\n    def test_hook_safety_rules(self):\n        for rule in (\n            "fabricate a result", "fake scarcity", "impersonate a customer quote",\n            "misstate product capability", "unsupported hypothesis as observed truth",\n        ):\n            self.assertIn(rule, self.content)\n\n    def test_editorial_plan_has_measurement_and_evidence(self):\n        for field in (\n            "audience segment", "awareness level", "distribution channel", "evidence basis",\n            "experiment hypothesis if unproven", "measurement expectation supplied to Performance",\n        ):\n            self.assertIn(field, self.content)\n\n    def test_seo_contract_forbids_invented_metrics(self):\n        for field in ("query/topic cluster", "search intent", "factual sources required", "risks of unsupported claims"):\n            self.assertIn(field, self.content)\n        self.assertIn("Never invent keyword volume", self.content)\n        self.assertIn("traffic forecasts", self.content)\n\n    def test_short_form_adaptation_requires_native_channel_behavior(self):\n        self.assertIn("native behavior of each channel", self.content)\n        self.assertIn("deliver one dominant idea", self.content)\n        self.assertIn("end with one clear CTA", self.content)\n\n    def test_experiment_contract_keeps_measurement_with_performance(self):\n        for field in (\n            "content variable being changed", "expected behavioral signal",\n            "guardrail or failure condition", "support, refutation, or inconclusive evidence",\n        ):\n            self.assertIn(field, self.content)\n        self.assertIn("Performance owns authoritative measurement", self.content)\n        self.assertIn("cannot self-certify a winner", self.content)\n\n    def test_collaboration_protocol_preserves_role_boundaries(self):\n        for heading in ("From Intelligence", "From CMO", "To Creative", "To Performance", "Back to CMO"):\n            self.assertIn(heading, self.content)\n        self.assertIn("Creative owns visual/production execution", self.content)\n\n    def test_learning_loop_does_not_overgeneralize(self):\n        self.assertIn("Goal -> evidence check -> content hypothesis", self.content)\n        self.assertIn("Do not convert a single successful post into a universal rule", self.content)\n        self.assertIn("Preserve scope, audience, channel, time, product, and evidence lineage", self.content)\n\n    def test_output_contract_is_structured_and_fail_safe(self):\n        for field in (\n            "OBJECTIVE", "AUDIENCE", "EVIDENCE_BASE", "KNOWN_UNKNOWNS", "MESSAGE_HIERARCHY",\n            "CONTENT_ASSET_OR_BRIEF", "CLAIMS_REQUIRING_PROOF", "HANDOFF_TARGET", "MEASUREMENT_QUESTION",\n        ):\n            self.assertIn(field, self.content)\n        self.assertIn("INSUFFICIENT EVIDENCE", self.content)\n\n    def test_permanent_five_asi_invariant(self):\n        for role in ("CMO", "Intelligence", "Content", "Creative", "Performance"):\n            self.assertIn(role, self.content)\n        self.assertIn("There is no permanent Strategist identity", self.content)\n        self.assertIn("no sixth Final CMO", self.content)\n        self.assertIn("compatibility inputs only", self.content)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
        encoding="utf-8",
    )
    changed.add(str(content_test))

    print("Canonical Content migration changed paths:")
    for rel in sorted(changed):
        print(" -", rel)
    print("Frozen hashes:", current_hashes)


if __name__ == "__main__":
    main()
