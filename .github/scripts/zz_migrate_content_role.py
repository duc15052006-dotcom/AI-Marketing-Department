from pathlib import Path

path = Path("runtime/engine.py")
s = path.read_text(encoding="utf-8")

replacements = {
    'user_prompt = f"Objective: {context.objective}\\nPositioning Strategy: {content_strategy}\\n\\n{evidence_section}".strip()':
        'user_prompt = f"Objective: {context.objective}\\nCMO Strategy & Positioning: {context.stage_outputs.get(\'cmo_initial\', {}).get(\'strategic_intent\', \'\')}\\nContent Messaging & Editorial Brief: {content_strategy}\\n\\n{evidence_section}".strip()',
    '"4. ## Creative Concepts, Ad Hooks & Video Scripts (from Creative)\\n"':
        '"4. ## Creative Visual Concepts, Storyboards & Multimedia Assets (from Creative)\\n"',
    'f"- Content Positioning: {content_out.get(\'positioning\', \'\')}\\n"':
        'f"- Content Strategy & Messaging: {content_out.get(\'content_strategy\', \'\')}\\n"',
}

for old, new in replacements.items():
    if old not in s:
        raise SystemExit(f"EXPECTED_PATTERN_MISSING: {old}")
    s = s.replace(old, new, 1)

# Canonical runtime must not actively execute the removed role. The sole
# historical method name is a deprecated API shim that delegates to Content.
for forbidden in (
    "RuntimeStage." + "STRATEGIST",
    'stage_outputs["' + "strategist" + '"]',
    '_call_agent_llm("' + "strategist" + '"',
    'agent="' + "STRATEGIST" + '"',
    'Content Positioning:',
    'Positioning Strategy: {content_strategy}',
):
    if forbidden in s:
        raise SystemExit(f"RUNTIME_ROLE_BOUNDARY_INCOMPLETE: {forbidden}")

if s.count("def execute_stage_strategist") != 1:
    raise SystemExit("LEGACY_SHIM_COUNT_INVALID")
if "Deprecated compatibility shim; executes canonical Content stage." not in s:
    raise SystemExit("LEGACY_SHIM_NOT_EXPLICIT")
if 'content_out.get(\'content_strategy\', \'\')' not in s:
    raise SystemExit("FINAL_CMO_CONTENT_HANDOFF_MISSING")

path.write_text(s, encoding="utf-8")
print("Content semantic ownership repair complete.")
