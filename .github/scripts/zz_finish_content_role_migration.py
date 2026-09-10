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
# Content inherits research/text/workspace-read responsibilities from the
# removed permanent role. Performance/CMO retain analytics/KPI/experiment
# authority; Content must not gain raw telemetry/attribution authority.
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

# No builtin capability is allowed to advertise the removed permanent agent.
for match in re.finditer(r"supported_agents\s*=\s*\[(.*?)\]", cap, flags=re.S):
    if "strategist" in match.group(1).lower():
        raise SystemExit("STALE_STRATEGIST_CAPABILITY_AUTHORITY: " + match.group(0))

cap_path.write_text(cap, encoding="utf-8")


# ---------------------------------------------------------------------------
# Stale test fixtures. These modules exercise the canonical current role, not
# legacy-deserialization compatibility. The dedicated canonical identity test
# remains untouched and is the sole regression for legacy STRATEGIST -> CONTENT.
# ---------------------------------------------------------------------------
test_files = [
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

# Active target fixtures must no longer reference the removed role as an exact
# identity literal. Legacy migration coverage lives in the excluded contract test.
for raw_path in test_files:
    text = Path(raw_path).read_text(encoding="utf-8")
    for forbidden in ('"STRATEGIST"', "'STRATEGIST'", '"strategist"', "'strategist'"):
        if forbidden in text:
            raise SystemExit(f"STALE_TARGET_FIXTURE {raw_path}: {forbidden}")

print("Production capability authority migrated to canonical Content.")
print("Migrated target fixtures:")
for raw_path in changed_tests:
    print(" -", raw_path)
