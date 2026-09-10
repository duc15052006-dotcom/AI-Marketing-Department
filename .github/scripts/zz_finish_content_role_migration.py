from pathlib import Path
import re


def replace_required(text: str, old: str, new: str, *, path: str, count: int | None = None) -> str:
    found = text.count(old)
    if found == 0:
        raise SystemExit(f"EXPECTED_PATTERN_MISSING {path}: {old!r}")
    if count is not None and found != count:
        raise SystemExit(f"EXPECTED_PATTERN_COUNT {path}: {old!r}: expected {count}, found {found}")
    return text.replace(old, new)


# ---------------------------------------------------------------------------
# Production capability authority.
# Content inherits evidence-gathering, text-creation, and workspace-read
# responsibilities from the removed permanent role. Performance/CMO retain
# raw analytics/KPI/experiment authority. Content must not gain attribution,
# live publishing, budget, image/video, or generic workspace-write authority.
# ---------------------------------------------------------------------------
cap_path = Path("tools/capabilities.py")
cap = cap_path.read_text(encoding="utf-8")

cap = replace_required(
    cap,
    'supported_agents=["intelligence", "strategist", "cmo"]',
    'supported_agents=["intelligence", "content", "cmo"]',
    path=str(cap_path),
    count=2,
)
cap = replace_required(
    cap,
    'supported_agents=["creative", "strategist", "cmo"]',
    'supported_agents=["creative", "content", "cmo"]',
    path=str(cap_path),
    count=1,
)
cap = replace_required(
    cap,
    'supported_agents=["performance", "cmo", "strategist"]',
    'supported_agents=["performance", "cmo"]',
    path=str(cap_path),
    count=3,
)
cap = replace_required(
    cap,
    'supported_agents=["cmo", "intelligence", "strategist", "creative", "performance"]',
    'supported_agents=["cmo", "intelligence", "content", "creative", "performance"]',
    path=str(cap_path),
    count=1,
)
cap = replace_required(
    cap,
    'supported_agents=["cmo", "intelligence", "performance", "strategist"]',
    'supported_agents=["cmo", "intelligence", "performance", "content"]',
    path=str(cap_path),
    count=1,
)

for match in re.finditer(r"supported_agents\s*=\s*\[(.*?)\]", cap, flags=re.S):
    if "strategist" in match.group(1).lower():
        raise SystemExit("STALE_STRATEGIST_CAPABILITY_AUTHORITY: " + match.group(0))

cap_path.write_text(cap, encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime RBAC authority.
# Content needs READ_ONLY for research/context and CREATE_LOCAL for local text
# generation. It deliberately does NOT inherit the removed Strategist role's
# ANALYTICS permission. Concrete capability allowlists remain the second gate.
# ---------------------------------------------------------------------------
security_path = Path("tools/security.py")
security = security_path.read_text(encoding="utf-8")
old_security = '''    "strategist": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.ANALYTICS,
    },'''
new_security = '''    "content": {
        PermissionLevel.READ_ONLY,
        PermissionLevel.CREATE_LOCAL,
    },'''
security = replace_required(
    security,
    old_security,
    new_security,
    path=str(security_path),
    count=1,
)
if '"strategist": {' in security.lower():
    raise SystemExit("STALE_STRATEGIST_RBAC_AUTHORITY")
if new_security not in security:
    raise SystemExit("CONTENT_RBAC_AUTHORITY_MISSING")
security_path.write_text(security, encoding="utf-8")


# ---------------------------------------------------------------------------
# Stale current-role test fixtures. These modules exercise the canonical current
# role, not legacy deserialization compatibility. The dedicated canonical
# identity regression remains untouched and continues to verify the narrow
# STRATEGIST -> CONTENT legacy ingress mapping.
# ---------------------------------------------------------------------------
test_files = [
    "tests/test_brain_action_intent_capability_binding_v1.py",
    "tests/test_brain_collaboration_intelligence_v1.py",
    "tests/test_brain_reasoning_policy_v1.py",
    "tests/test_brain_cognitive_contract_v1.py",
    "tests/test_brain_action_intent_execution_intent_provenance_v1.py",
    "tests/test_brain_canonical_action_intent_tool_gateway_v1.py",
    "tests/test_brain_action_intent_receipt_provenance_v1.py",
    "tests/test_brain_observation_action_intent_provenance_v1.py",
    "tests/test_brain_runtime_canonical_action_intent_handoff_v1.py",
]

literal_replacements = (
    ('"STRATEGIST"', '"CONTENT"'),
    ("'STRATEGIST'", "'CONTENT'"),
    ('"strategist"', '"content"'),
    ("'strategist'", "'content'"),
)

changed_tests = []
for raw_path in test_files:
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    original = text
    for old, new in literal_replacements:
        text = text.replace(old, new)
    if text != original:
        path.write_text(text, encoding="utf-8")
        changed_tests.append(raw_path)

if not changed_tests:
    raise SystemExit("NO_STALE_TARGET_TEST_FIXTURES_FOUND")

for raw_path in test_files:
    text = Path(raw_path).read_text(encoding="utf-8")
    for forbidden in ('"STRATEGIST"', "'STRATEGIST'", '"strategist"', "'strategist'"):
        if forbidden in text:
            raise SystemExit(f"STALE_TARGET_FIXTURE {raw_path}: {forbidden}")

print("Production capability authority migrated to canonical Content.")
print("Runtime RBAC migrated to canonical Content without analytics escalation.")
print("Migrated target fixtures:")
for raw_path in changed_tests:
    print(" -", raw_path)
