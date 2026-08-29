"""R1 launcher for full defect batch V1.

Correct one overly-generic migration anchor before executing the audited batch.
The original migration stays immutable for audit history.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORIGINAL = ROOT / "tools" / "dev" / "apply_full_defect_batch_v1.py"
source = ORIGINAL.read_text(encoding="utf-8")
old = '''replace_exact(
    "runtime/engine.py",
    \'\'\'        emitter = self._get_emitter(context)\n        if emitter:\n\'\'\',
    \'\'\'        context.working_state["research_depth"] = str(research_depth or "STANDARD").upper()\n        emitter = self._get_emitter(context)\n        if emitter:\n\'\'\',
    count=1,
)
'''
new = '''replace_exact(
    "runtime/engine.py",
    \'\'\'            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n\n        emitter = self._get_emitter(context)\n        if emitter:\n\'\'\',
    \'\'\'            mode=ProgressMode.RESEARCH_INQUIRY.value,\n        )\n\n        context.working_state["research_depth"] = str(research_depth or "STANDARD").upper()\n        emitter = self._get_emitter(context)\n        if emitter:\n\'\'\',
)
'''
if source.count(old) != 1:
    raise RuntimeError(f"R1 migration drift: expected generic research-depth block once, found {source.count(old)}")
source = source.replace(old, new)
exec(compile(source, str(ORIGINAL), "exec"), {"__name__": "__main__", "__file__": str(ORIGINAL)})
