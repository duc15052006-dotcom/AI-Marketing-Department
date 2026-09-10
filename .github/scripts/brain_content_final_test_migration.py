from pathlib import Path

OLD_HASH = "26be7c5a2aa3c388defec7fe92162d0082c34ca6609f17c692704863ce4ea3c9"
NEW_HASH = "0501d698f6b33f13eee9b75bb304dc93ff46aeaa66679ab3ffe879ef1ed0c604"


def replace(path: str, old: str, new: str, *, exact: int | None = None, minimum: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if exact is not None and count != exact:
        raise SystemExit(f"{path}: expected {exact} matches for {old!r}, found {count}")
    if exact is None and count < minimum:
        raise SystemExit(f"{path}: expected at least {minimum} matches for {old!r}, found {count}")
    p.write_text(text.replace(old, new), encoding="utf-8")
    print(f"{path}: replaced {count} occurrence(s)")


# Current Content DNA no longer contains the historical Marketing Strategist title.
replace(
    "tests/test_collaboration_adversarial_final.py",
    '("content", "Marketing Strategist"),',
    '("content", "Content ASI"),',
    exact=1,
)
replace(
    "tests/test_collaboration_integrity_audit.py",
    '("content", "Marketing Strategist"),',
    '("content", "Content ASI"),',
    exact=1,
)
replace(
    "tests/test_phase1a_runtime_integrity.py",
    'elif "you are the marketing strategist" in sys_content:',
    'elif "content asi" in sys_content:',
    exact=1,
)

# Canonical AgentRole consumers must use CONTENT, not a removed enum member.
for path in (
    "tests/test_collaboration_definition.py",
    "tests/test_model_execution_bridge.py",
    "tests/test_schemas.py",
):
    replace(path, "AgentRole.STRATEGIST", "AgentRole.CONTENT")

replace(
    "tests/test_collaboration_definition.py",
    '{"CMO", "INTELLIGENCE", "STRATEGIST", "CREATIVE", "PERFORMANCE"}',
    '{"CMO", "INTELLIGENCE", "CONTENT", "CREATIVE", "PERFORMANCE"}',
    exact=1,
)
replace("tests/test_collaboration_definition.py", "Handoff to Strategist", "Handoff to Content")

# Migrate active collaboration tests to the canonical Content entrypoint while
# explicitly allowing only the deprecated compatibility shim as a non-canonical extra method.
audit_path = Path("tests/test_collaboration_integrity_audit.py")
audit = audit_path.read_text(encoding="utf-8")
old_block = """        self.assertEqual(stage_methods, {
            \"execute_stage_cmo_initial\",      # agent 1 (initial pass)
            \"execute_stage_intelligence\",     # agent 2
            \"execute_stage_strategist\",       # agent 3
            \"execute_stage_creative\",         # agent 4
            \"execute_stage_performance\",      # agent 5
            \"execute_stage_final_cmo\",        # agent 1 (final pass) - NOT a sixth agent
        })"""
new_block = """        canonical_stage_methods = {
            \"execute_stage_cmo_initial\",      # agent 1 (initial pass)
            \"execute_stage_intelligence\",     # agent 2
            \"execute_stage_content\",          # agent 3
            \"execute_stage_creative\",         # agent 4
            \"execute_stage_performance\",      # agent 5
            \"execute_stage_final_cmo\",        # agent 1 (final pass) - NOT a sixth agent
        }
        self.assertTrue(canonical_stage_methods.issubset(stage_methods))
        legacy_compat_stage = \"execute_stage_\" + \"strategist\"
        self.assertEqual(stage_methods - canonical_stage_methods, {legacy_compat_stage})"""
if audit.count(old_block) != 1:
    raise SystemExit("collaboration integrity: canonical stage-method block precondition mismatch")
audit = audit.replace(old_block, new_block)
old_len = """        stage_methods = {m for m in dir(rt) if m.startswith(\"execute_stage_\")}
        self.assertEqual(len(stage_methods), 6)"""
new_len = """        stage_methods = {m for m in dir(rt) if m.startswith(\"execute_stage_\")}
        canonical_stage_methods = {
            \"execute_stage_cmo_initial\", \"execute_stage_intelligence\", \"execute_stage_content\",
            \"execute_stage_creative\", \"execute_stage_performance\", \"execute_stage_final_cmo\",
        }
        self.assertTrue(canonical_stage_methods.issubset(stage_methods))
        legacy_compat_stage = \"execute_stage_\" + \"strategist\"
        self.assertEqual(stage_methods - canonical_stage_methods, {legacy_compat_stage})"""
if audit.count(old_len) != 1:
    raise SystemExit("collaboration integrity: stage count precondition mismatch")
audit = audit.replace(old_len, new_len)
legacy_call_count = audit.count("execute_stage_strategist(ctx)")
if legacy_call_count < 1:
    raise SystemExit("collaboration integrity: expected legacy stage calls to migrate")
audit = audit.replace("execute_stage_strategist(ctx)", "execute_stage_content(ctx)")
audit = audit.replace("Strategist must be invoked", "Content must be invoked")
audit_path.write_text(audit, encoding="utf-8")
print(f"tests/test_collaboration_integrity_audit.py: migrated {legacy_call_count} legacy stage call(s)")

# Instrument the method execute_run actually calls, not the deprecated shim.
replace(
    "tests/test_prod_core_authority_01a.py",
    '("content", "execute_stage_strategist"),',
    '("content", "execute_stage_content"),',
    exact=1,
)
replace(
    "tests/test_prod_runtime_01_single_run_authority.py",
    'self.assertEqual(final_cmo.get("failed_stage"), "STRATEGIST")',
    'self.assertEqual(final_cmo.get("failed_stage"), "CONTENT")',
    exact=1,
)

# Performance DNA changed intentionally as part of the reviewed Content authority migration.
for path in (
    "tests/test_applicationization_v1.py",
    "tests/test_chat_first_app_v1.py",
    "tests/test_chat_persistence_v1.py",
    "tests/test_phase5_1_foundation.py",
    "tests/test_phase5_2_runtime_integration.py",
    "tests/test_phase6_1_v1_connectors_and_workspace.py",
    "tests/test_phase6_2_pilot_and_v1_release.py",
):
    replace(path, OLD_HASH, NEW_HASH)

# Fail closed if active tests still directly require the removed canonical enum member.
for path in (
    "tests/test_collaboration_definition.py",
    "tests/test_model_execution_bridge.py",
    "tests/test_schemas.py",
):
    if "AgentRole.STRATEGIST" in Path(path).read_text(encoding="utf-8"):
        raise SystemExit(f"{path}: stale AgentRole.STRATEGIST remains")

print("Canonical Content regression migration applied successfully.")
