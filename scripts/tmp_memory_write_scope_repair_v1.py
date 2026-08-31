from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")

old = '''        completed_at = datetime.now(timezone.utc)\n\n        # 1. Propose Memory Candidates only if run completed successfully.\n'''
new = '''        completed_at = datetime.now(timezone.utc)\n\n        # Decision-memory write scope is derived from immutable RuntimeContext\n        # authority, never mutable working_state hints. Prefer the most-specific\n        # exact project/business/trusted migration scope; GLOBAL is the explicit\n        # fallback only when the run has no private memory scope.\n        memory_scope_plan = build_runtime_canonical_scope_plan(context)\n        memory_write_scope = (\n            memory_scope_plan.memory_scope_keys[0]\n            if memory_scope_plan.memory_scope_keys\n            else "GLOBAL"\n        )\n\n        # 1. Propose Memory Candidates only if run completed successfully.\n'''
if text.count(old) != 1:
    raise SystemExit(f"ANCHOR_COUNT_MISMATCH completed_at: {text.count(old)}")
text = text.replace(old, new, 1)

old_scope = '''                        scope=(str(context.working_state.get("memory_scope") or "GLOBAL").strip() or "GLOBAL"),\n'''
new_scope = '''                        scope=memory_write_scope,\n'''
if text.count(old_scope) != 1:
    raise SystemExit(f"ANCHOR_COUNT_MISMATCH memory_scope: {text.count(old_scope)}")
text = text.replace(old_scope, new_scope, 1)

path.write_text(text, encoding="utf-8")
print("memory write scope candidate patch applied")
