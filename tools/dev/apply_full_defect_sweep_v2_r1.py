"""R1 launcher for the asserted full defect sweep migration."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_full_defect_sweep_v2.py"
source = ORIGINAL.read_text(encoding="utf-8")

ambiguous = '''replace_exact(
    "runtime/engine.py",
    ''' + "'''" + '''        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    ''' + "'''" + '''        depth_norm = str(research_depth or "STANDARD").upper()\n        context.working_state["research_depth"] = depth_norm if depth_norm in {"QUICK", "STANDARD", "DEEP"} else "STANDARD"\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    count=1,
)
'''
specific = '''replace_exact(
    "runtime/engine.py",
    ''' + "'''" + '''            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
    ''' + "'''" + '''            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n        depth_norm = str(research_depth or "STANDARD").upper()\n        context.working_state["research_depth"] = depth_norm if depth_norm in {"QUICK", "STANDARD", "DEEP"} else "STANDARD"\n\n        emitter = self._get_emitter(context)\n        if emitter:\n''' + "'''" + ''',
)
'''
if source.count(ambiguous) != 1:
    raise RuntimeError("R1_ASSERTION_FAILED: migration emitter block drift")
source = source.replace(ambiguous, specific)
exec(compile(source, str(ORIGINAL), "exec"), {"__name__": "__main__", "__file__": str(ORIGINAL)})
