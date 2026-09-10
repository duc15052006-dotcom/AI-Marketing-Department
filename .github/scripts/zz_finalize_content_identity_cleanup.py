from pathlib import Path


def replace_required(text: str, old: str, new: str, *, path: str, count: int = 1) -> str:
    found = text.count(old)
    if found != count:
        raise SystemExit(
            f"EXPECTED_PATTERN_COUNT {path}: expected {count}, found {found}: {old!r}"
        )
    return text.replace(old, new)


# ---------------------------------------------------------------------------
# Intelligence: evidence/research only. Strategy belongs to CMO, text/content
# to Content, multimedia production to Creative, live execution to Runtime/Body.
# ---------------------------------------------------------------------------
intelligence_path = Path(".agents/agents/intelligence/agent.md")
intelligence = intelligence_path.read_text(encoding="utf-8")
for old, new in [
    (
        "- **NOT** the final strategic decision-maker (delegate strategy formulation, positioning, and budget allocation to **CMO** and **Content**).",
        "- **NOT** the final strategic decision-maker (delegate strategy formulation, positioning, offer boundaries, and budget allocation to **CMO**).",
    ),
    (
        "- **NOT** the primary copywriter or scriptwriter (delegate concept development, ad copy, and scripts to **Creative**).",
        "- **NOT** the primary content strategist, copywriter, or scriptwriter (delegate messaging architecture, concepts, hooks, ad copy, scripts, and CTA wording to **Content**).",
    ),
    (
        "- **NOT** the creative production director (delegate multimedia asset rendering and timelines to **Creative Engine**).",
        "- **NOT** the creative production director (delegate visual concepts, storyboards, multimedia asset rendering, and production timelines to **Creative**).",
    ),
    (
        "- **NOT** the publishing operator or ad campaign manager (delegate ad setup and deployment to **Performance** under strict human authorization).",
        "- **NOT** a publishing operator or live ad campaign executor; external setup and deployment must pass governed runtime/Body policy and required human approval.",
    ),
]:
    intelligence = replace_required(intelligence, old, new, path=str(intelligence_path))
intelligence_path.write_text(intelligence, encoding="utf-8")


# ---------------------------------------------------------------------------
# CMO: governance/strategy owner, not text/media/live execution specialist.
# ---------------------------------------------------------------------------
cmo_path = Path(".agents/agents/cmo/agent.md")
cmo = cmo_path.read_text(encoding="utf-8")
for old, new in [
    (
        "- **NOT** the primary copywriter (delegate concept, hook, and copy generation to **Creative**).",
        "- **NOT** the primary content strategist or copywriter (delegate messaging architecture, verbal concepts, hooks, copy, scripts, CTA wording, and editorial adaptation to **Content**).",
    ),
    (
        "- **NOT** the primary video creator (delegate video timeline assembly and asset synthesis to **Creative Engine**).",
        "- **NOT** the primary media producer (delegate visual concepts, storyboards, video timeline assembly, and image/video/audio asset synthesis to **Creative**).",
    ),
    (
        "- **NOT** the publishing worker (delegate platform payload preparation to **Performance** under strict autonomy gates).",
        "- **NOT** a publishing worker or live campaign executor; external platform actions must pass governed runtime/Body policy and required human approval.",
    ),
]:
    cmo = replace_required(cmo, old, new, path=str(cmo_path))
cmo_path.write_text(cmo, encoding="utf-8")


# ---------------------------------------------------------------------------
# Stale identity regression: permanent Brain identity is Content, not Strategist.
# ---------------------------------------------------------------------------
learning_path = Path("tests/test_brain_learning_consolidation_v1.py")
learning = learning_path.read_text(encoding="utf-8")
learning = replace_required(
    learning,
    '{"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"}',
    '{"CMO", "INTELLIGENCE", "CONTENT", "CREATIVE", "PERFORMANCE"}',
    path=str(learning_path),
)
learning_path.write_text(learning, encoding="utf-8")


# ---------------------------------------------------------------------------
# Creative prerequisite fixture: Content is the canonical predecessor and the
# __new__ fixture must model the constructor-default trusted resolver seam.
# ---------------------------------------------------------------------------
prereq_path = Path("tests/test_creative_prerequisite_tool_gate_adversarial_v1.py")
prereq = prereq_path.read_text(encoding="utf-8")
for old, new in [
    (
        "Invariant: once Strategist has FAILED, Creative must not invoke downstream tools.",
        "Invariant: once Content has FAILED, Creative must not invoke downstream tools.",
    ),
    (
        "def test_failed_strategist_prevents_creative_tool_execution(self) -> None:",
        "def test_failed_content_prevents_creative_tool_execution(self) -> None:",
    ),
    (
        "        runtime.context_compiler = _NoopContextCompiler()\n        runtime._executed_tool_idempotency_keys = {}",
        "        runtime.context_compiler = _NoopContextCompiler()\n        runtime.brain_action_authority_resolver = None\n        runtime._executed_tool_idempotency_keys = {}",
    ),
    (
        '            objective="Do not continue when the strategy prerequisite has failed.",',
        '            objective="Do not continue when the content prerequisite has failed.",',
    ),
    (
        '        context.stage_outputs["strategist"] = {\n            "stage": "STRATEGIST",\n            "agent": "strategist",',
        '        context.stage_outputs["content"] = {\n            "stage": "CONTENT",\n            "agent": "content",',
    ),
    (
        '            "Creative must fail closed before image_generation when Strategist failed.",',
        '            "Creative must fail closed before image_generation when Content failed.",',
    ),
]:
    prereq = replace_required(prereq, old, new, path=str(prereq_path))
prereq_path.write_text(prereq, encoding="utf-8")


# ---------------------------------------------------------------------------
# The runtime has six canonical stages for five permanent agents because CMO is
# reused for final synthesis. A deprecated strategist compatibility method is a
# shim, not a sixth agent/stage identity, and may eventually disappear.
# ---------------------------------------------------------------------------
handoff_path = Path("tests/test_creative_performance_true_handoff.py")
handoff = handoff_path.read_text(encoding="utf-8")
handoff = replace_required(
    handoff,
    '        self.assertEqual(len({m for m in dir(rt) if m.startswith("execute_stage_")}), 6)',
    '''        canonical_stage_methods = {
            "execute_stage_cmo_initial",
            "execute_stage_intelligence",
            "execute_stage_content",
            "execute_stage_creative",
            "execute_stage_performance",
            "execute_stage_final_cmo",
        }
        stage_methods = {m for m in dir(rt) if m.startswith("execute_stage_")}
        self.assertEqual(
            stage_methods - {"execute_stage_strategist"},
            canonical_stage_methods,
            "Only six canonical stages may represent the five permanent ASIs; "
            "execute_stage_strategist is a deprecated compatibility shim, not an agent.",
        )''',
    path=str(handoff_path),
)
handoff_path.write_text(handoff, encoding="utf-8")


# ---------------------------------------------------------------------------
# Extend semantic prompt regression so Intelligence/CMO cannot drift back to
# Strategist-era specialist overlap.
# ---------------------------------------------------------------------------
boundary_path = Path("tests/test_agent_prompt_semantic_role_boundaries_v1.py")
boundary = boundary_path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n    unittest.main()\n'
addition = '''

    def test_intelligence_handoffs_strategy_content_media_and_execution_correctly(self):
        text = _agent("intelligence")
        self.assertIn("strategy formulation, positioning, offer boundaries, and budget allocation to **CMO**", text)
        self.assertIn("messaging architecture, concepts, hooks, ad copy, scripts, and CTA wording to **Content**", text)
        self.assertIn("visual concepts, storyboards, multimedia asset rendering, and production timelines to **Creative**", text)
        self.assertIn("governed runtime/Body policy", text)
        self.assertNotIn("strategy formulation, positioning, and budget allocation to **CMO** and **Content**", text)
        self.assertNotIn("concept development, ad copy, and scripts to **Creative**", text)
        self.assertNotIn("ad setup and deployment to **Performance**", text)

    def test_cmo_delegates_text_media_and_live_execution_without_role_overlap(self):
        text = _agent("cmo")
        self.assertIn("messaging architecture, verbal concepts, hooks, copy, scripts, CTA wording, and editorial adaptation to **Content**", text)
        self.assertIn("visual concepts, storyboards, video timeline assembly, and image/video/audio asset synthesis to **Creative**", text)
        self.assertIn("external platform actions must pass governed runtime/Body policy", text)
        self.assertNotIn("delegate concept, hook, and copy generation to **Creative**", text)
        self.assertNotIn("delegate platform payload preparation to **Performance**", text)
'''
boundary = replace_required(
    boundary,
    marker,
    addition + marker,
    path=str(boundary_path),
)
boundary_path.write_text(boundary, encoding="utf-8")


print("Final Content identity cleanup applied.")
print("Repaired Intelligence/CMO role handoffs and three stale regressions.")
