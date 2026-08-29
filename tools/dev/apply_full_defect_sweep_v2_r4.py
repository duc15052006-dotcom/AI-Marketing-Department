"""R4 launcher: scope stale runtime-test repairs without weakening assertions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
R3 = ROOT / "tools" / "dev" / "apply_full_defect_sweep_v2_r1.py"
source = R3.read_text(encoding="utf-8")
old = '''runtime_test = ROOT / "tests" / "test_prod_runtime_01_single_run_authority.py"
r = runtime_test.read_text(encoding="utf-8")
old_assert = '        self.assertEqual(final_cmo.get("status"), "FAILED")\\n'
if r.count(old_assert) != 1:
    raise RuntimeError(f"R3_ASSERTION_FAILED: stale final-cmo assertion count={r.count(old_assert)}")
runtime_test.write_text(r.replace(old_assert, '        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")\\n'), encoding="utf-8")
'''
new = '''runtime_test = ROOT / "tests" / "test_prod_runtime_01_single_run_authority.py"
r = runtime_test.read_text(encoding="utf-8")
old_mid = ''' + '"""' + '''        self.assertEqual(final_cmo.get("status"), "FAILED")
        self.assertIn("PREVIOUS_STAGE_FAILED", final_cmo.get("reason", ""))
''' + '"""' + '''
new_mid = ''' + '"""' + '''        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")
        self.assertNotIn("PREVIOUS_STAGE_FAILED", final_cmo.get("reason", ""))
''' + '"""' + '''
if r.count(old_mid) != 1:
    raise RuntimeError(f"R4_ASSERTION_FAILED: middle-stage contract drift count={r.count(old_mid)}")
r = r.replace(old_mid, new_mid)
old_leak = '        self.assertIn("UNEXPECTED_PIPELINE_CRASH", final_cmo.get("reason", ""))\\n'
if r.count(old_leak) != 1:
    raise RuntimeError(f"R4_ASSERTION_FAILED: exception leak assertion drift count={r.count(old_leak)}")
r = r.replace(old_leak, '        self.assertNotIn("UNEXPECTED_PIPELINE_CRASH", final_cmo.get("reason", ""))\\n')
runtime_test.write_text(r, encoding="utf-8")
'''
if source.count(old) != 1:
    raise RuntimeError("R4_ASSERTION_FAILED: R3 runtime test patch drift")
source = source.replace(old, new)
exec(compile(source, str(R3), "exec"), {"__name__": "__main__", "__file__": str(R3)})
print("FULL_DEFECT_SWEEP_V2_R4_PATCH_APPLIED")
