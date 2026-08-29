"""R1 launcher for the asserted Agent Hardening V2 production patch.

The first workflow proved that the two routing sites have different indentation
because they live in different methods.  Keep the original migration immutable
for auditability, execute it with the corrected expected count in-memory, then
patch the second (synchronous) route explicitly and fail closed on drift.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_agent_hardening_v2.py"

source = ORIGINAL.read_text(encoding="utf-8")
needle = 'replace_exact("app_api/server.py", route_block, resolved_route_block, expected_count=2)'
replacement = 'replace_exact("app_api/server.py", route_block, resolved_route_block, expected_count=1)'
if source.count(needle) != 1:
    raise RuntimeError("R1_PATCH_ASSERTION_FAILED: original route-count assertion changed")
source = source.replace(needle, replacement)
exec(compile(source, str(ORIGINAL), "exec"), {"__name__": "__main__", "__file__": str(ORIGINAL)})

server_path = ROOT / "app_api" / "server.py"
server = server_path.read_text(encoding="utf-8")
old = '''            decision = APP_BACKEND.conversation_router.route(
                message=user_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
'''
new = '''            resolved_followup = resolve_followup(user_text, session.messages)
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
count = server.count(old)
if count != 1:
    raise RuntimeError(f"R1_PATCH_ASSERTION_FAILED app_api/server.py sync route: expected 1, found {count}")
server_path.write_text(server.replace(old, new), encoding="utf-8")
print("AGENT_HARDENING_V2_R1_PATCH_APPLIED")
