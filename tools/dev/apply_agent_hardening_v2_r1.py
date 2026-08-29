"""R1 launcher for the asserted Agent Hardening V2 production patch.

The first workflow proved that streaming and synchronous routing sites use
different indentation. Keep the original migration immutable for auditability,
execute it with counts corrected only for the streaming site, then patch the
synchronous site explicitly and fail closed on source drift.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_agent_hardening_v2.py"

source = ORIGINAL.read_text(encoding="utf-8")
replacements = {
    'replace_exact("app_api/server.py", route_block, resolved_route_block, expected_count=2)':
        'replace_exact("app_api/server.py", route_block, resolved_route_block, expected_count=1)',
    '''    "                        objective=user_text,\\n",\n    "                        objective=effective_text,\\n",\n    expected_count=4,''':
        '''    "                        objective=user_text,\\n",\n    "                        objective=effective_text,\\n",\n    expected_count=2,''',
}
for needle, replacement in replacements.items():
    if source.count(needle) != 1:
        raise RuntimeError(f"R1_PATCH_ASSERTION_FAILED: migration source drift for {needle[:70]!r}")
    source = source.replace(needle, replacement)

exec(compile(source, str(ORIGINAL), "exec"), {"__name__": "__main__", "__file__": str(ORIGINAL)})

# The original migration is retained as an audit record. Its generated skill
# separator contains escaped quote characters; normalize generated production
# source before syntax validation.
engine_path = ROOT / "runtime" / "engine.py"
engine = engine_path.read_text(encoding="utf-8")
bad_separator = '            + \\"\\n\\n\\"\n'
good_separator = '            + "\\n\\n"\n'
if engine.count(bad_separator) != 1:
    raise RuntimeError(
        f"R1_PATCH_ASSERTION_FAILED runtime/engine.py skill separator: expected 1, found {engine.count(bad_separator)}"
    )
engine_path.write_text(engine.replace(bad_separator, good_separator), encoding="utf-8")

server_path = ROOT / "app_api" / "server.py"
server = server_path.read_text(encoding="utf-8")

old_route = '''            decision = APP_BACKEND.conversation_router.route(
                message=user_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
'''
new_route = '''            resolved_followup = resolve_followup(user_text, session.messages)
            effective_text = resolved_followup.resolved_objective
            decision = APP_BACKEND.conversation_router.route(
                message=effective_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
            if resolved_followup.route_hint:
                decision.intent = ConversationIntent(resolved_followup.route_hint)
                decision.confidence = 0.99
                decision.reason_code = resolved_followup.reason_code
                decision.metadata = dict(decision.metadata or {})
                decision.metadata.update({
                    "followup_kind": resolved_followup.kind.value,
                    "research_depth": resolved_followup.research_depth.value,
                    "referenced_message_ids": list(resolved_followup.referenced_message_ids),
                })
'''
if server.count(old_route) != 1:
    raise RuntimeError(
        f"R1_PATCH_ASSERTION_FAILED app_api/server.py sync route: expected 1, found {server.count(old_route)}"
    )
server = server.replace(old_route, new_route)

old_objective = "                    objective=user_text,\n"
new_objective = "                    objective=effective_text,\n"
if server.count(old_objective) != 2:
    raise RuntimeError(
        f"R1_PATCH_ASSERTION_FAILED app_api/server.py sync objectives: expected 2, found {server.count(old_objective)}"
    )
server = server.replace(old_objective, new_objective)
server_path.write_text(server, encoding="utf-8")

print("AGENT_HARDENING_V2_R1_PATCH_APPLIED")
