"""R2 launcher for the asserted full defect sweep migration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_full_defect_sweep_v2.py"
source = ORIGINAL.read_text(encoding="utf-8")

# Replace the one ambiguous runtime emitter migration with a method-scoped one.
ambiguous_runtime = '''replace_exact(
    "runtime/engine.py",
    ''' + "'''" + '''        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    ''' + "'''" + '''        depth_norm = str(research_depth or "STANDARD").upper()\n        context.working_state["research_depth"] = depth_norm if depth_norm in {"QUICK", "STANDARD", "DEEP"} else "STANDARD"\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    count=1,
)
'''
specific_runtime = '''replace_exact(
    "runtime/engine.py",
    ''' + "'''" + '''            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    ''' + "'''" + '''            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n        depth_norm = str(research_depth or "STANDARD").upper()\n        context.working_state["research_depth"] = depth_norm if depth_norm in {"QUICK", "STANDARD", "DEEP"} else "STANDARD"\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
)
'''
if source.count(ambiguous_runtime) != 1:
    raise RuntimeError("R2_ASSERTION_FAILED: runtime emitter migration drift")
source = source.replace(ambiguous_runtime, specific_runtime)

# Remove the ambiguous server replacement from the generated migration; apply
# it directly below with the surrounding run_research_inquiry call as anchor.
ambiguous_server = '''replace_exact(
    "app_api/server.py",
    ''' + "'''" + '''                        progress_sink=bridge.send_progress,\n                        text_delta_sink=bridge.send_delta,\n                    )\n''' + "'''" + ''',
    ''' + "'''" + '''                        progress_sink=bridge.send_progress,\n                        text_delta_sink=bridge.send_delta,\n                        research_depth=resolved_followup.research_depth.value,\n                    )\n''' + "'''" + ''',
    count=1,
)
'''
if source.count(ambiguous_server) != 1:
    raise RuntimeError("R2_ASSERTION_FAILED: server migration drift")
source = source.replace(ambiguous_server, "")

exec(compile(source, str(ORIGINAL), "exec"), {"__name__": "__main__", "__file__": str(ORIGINAL)})

server_path = ROOT / "app_api" / "server.py"
server = server_path.read_text(encoding="utf-8")
old = '''                    ctx, intel_out, artifact = APP_BACKEND.runtime.run_research_inquiry(
                        objective=effective_text,
                        business_id=session.optional_business_id or "BIZ_AD_HOC_EXPLORATION",
                        chat_id=chat_id,
                        project_id=session.optional_project_id,
                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                    )
'''
new = '''                    ctx, intel_out, artifact = APP_BACKEND.runtime.run_research_inquiry(
                        objective=effective_text,
                        business_id=session.optional_business_id or "BIZ_AD_HOC_EXPLORATION",
                        chat_id=chat_id,
                        project_id=session.optional_project_id,
                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                        research_depth=resolved_followup.research_depth.value,
                    )
'''
if server.count(old) != 1:
    raise RuntimeError(f"R2_ASSERTION_FAILED: streaming research call count={server.count(old)}")
server_path.write_text(server.replace(old, new), encoding="utf-8")
print("FULL_DEFECT_SWEEP_V2_R2_PATCH_APPLIED")
