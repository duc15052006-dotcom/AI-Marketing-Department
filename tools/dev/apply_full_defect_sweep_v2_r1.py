"""R3 launcher for the asserted full defect sweep migration."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_full_defect_sweep_v2.py"
source = ORIGINAL.read_text(encoding="utf-8")

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
    raise RuntimeError("R3_ASSERTION_FAILED: runtime emitter migration drift")
source = source.replace(ambiguous_runtime, specific_runtime)

ambiguous_server = '''replace_exact(
    "app_api/server.py",
    ''' + "'''" + '''                        progress_sink=bridge.send_progress,\n                        text_delta_sink=bridge.send_delta,\n                    )\n''' + "'''" + ''',
    ''' + "'''" + '''                        progress_sink=bridge.send_progress,\n                        text_delta_sink=bridge.send_delta,\n                        research_depth=resolved_followup.research_depth.value,\n                    )\n''' + "'''" + ''',
    count=1,
)
'''
if source.count(ambiguous_server) != 1:
    raise RuntimeError("R3_ASSERTION_FAILED: server migration drift")
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
new = old.replace("                        text_delta_sink=bridge.send_delta,\n", "                        text_delta_sink=bridge.send_delta,\n                        research_depth=resolved_followup.research_depth.value,\n")
if server.count(old) != 1:
    raise RuntimeError(f"R3_ASSERTION_FAILED: streaming research call count={server.count(old)}")
server_path.write_text(server.replace(old, new), encoding="utf-8")

# Regression tests themselves had stale dict assumptions after RuntimeProgressEvent became typed.
test_path = ROOT / "tests" / "test_prod_workflow_failure_semantics_01.py"
t = test_path.read_text(encoding="utf-8")
repls = {
    'e.get("stage") == "FINAL_CMO" and e.get("event_type") == "STAGE_STARTED"': 'getattr(e, "stage", None) == "FINAL_CMO" and getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", None)) == "STAGE_STARTED"',
    'e.get("stage") == "CMO_INITIAL" and e.get("event_type") == "STAGE_STARTED"': 'getattr(e, "stage", None) == "CMO_INITIAL" and getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", None)) == "STAGE_STARTED"',
    'e.get("stage") == "CMO_INITIAL" and e.get("event_type") == "RUN_FAILED"': 'getattr(e, "stage", None) == "CMO_INITIAL" and getattr(getattr(e, "event_type", None), "value", getattr(e, "event_type", None)) == "RUN_FAILED"',
}
for old_expr, new_expr in repls.items():
    if old_expr not in t:
        raise RuntimeError(f"R3_ASSERTION_FAILED: progress test drift {old_expr}")
    t = t.replace(old_expr, new_expr)
test_path.write_text(t, encoding="utf-8")

runtime_test = ROOT / "tests" / "test_prod_runtime_01_single_run_authority.py"
r = runtime_test.read_text(encoding="utf-8")
old_assert = '        self.assertEqual(final_cmo.get("status"), "FAILED")\n'
if r.count(old_assert) != 1:
    raise RuntimeError(f"R3_ASSERTION_FAILED: stale final-cmo assertion count={r.count(old_assert)}")
runtime_test.write_text(r.replace(old_assert, '        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")\n'), encoding="utf-8")

# Generic media/analytics adapters are placeholders only: fail closed instead of reporting fake success.
adapters_path = ROOT / "tools" / "adapters.py"
a = adapters_path.read_text(encoding="utf-8")
media_pattern = r'class MediaCreationAdapter\(BaseCapabilityAdapter\):.*?\n\nclass PublishingAdapter'
media_replacement = '''class MediaCreationAdapter(BaseCapabilityAdapter):
    """Placeholder media adapter. A real connector must be registered in production."""
    def __init__(self, name: str = "image_gen_adapter") -> None:
        self._name = name
    @property
    def adapter_name(self) -> str:
        return self._name
    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return AdapterResult(success=False, error_code="REAL_MEDIA_CONNECTOR_REQUIRED", error_message="No real media generation connector is configured.", execution_mode=ExecutionMode.MOCK)


class PublishingAdapter'''
a, n = re.subn(media_pattern, media_replacement, a, count=1, flags=re.S)
if n != 1:
    raise RuntimeError("R3_ASSERTION_FAILED: media adapter class drift")
analytics_pattern = r'class AnalyticsAdapter\(BaseCapabilityAdapter\):.*?\n\nclass FileStorageAdapter'
analytics_replacement = '''class AnalyticsAdapter(BaseCapabilityAdapter):
    """Placeholder analytics adapter. Production must bind a real deterministic connector."""
    def __init__(self, name: str = "analytics_adapter") -> None:
        self._name = name
    @property
    def adapter_name(self) -> str:
        return self._name
    def execute(self, capability_id: str, parameters: Dict[str, Any], timeout_seconds: float = 30.0, *, run_id: str = "", business_id: str = "", project_id: str = "") -> AdapterResult:
        return AdapterResult(success=False, error_code="REAL_ANALYTICS_CONNECTOR_REQUIRED", error_message="No real analytics connector is configured.", execution_mode=ExecutionMode.MOCK)


class FileStorageAdapter'''
a, n = re.subn(analytics_pattern, analytics_replacement, a, count=1, flags=re.S)
if n != 1:
    raise RuntimeError("R3_ASSERTION_FAILED: analytics adapter class drift")
adapters_path.write_text(a, encoding="utf-8")

print("FULL_DEFECT_SWEEP_V2_R3_PATCH_APPLIED")
