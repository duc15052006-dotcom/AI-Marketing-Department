"""Post-sweep test-fixture alignment for certified production semantics.

No production assertions are weakened.  The changes make two historical tests
exercise the new contracts explicitly:
- an unhandled upstream crash means Final CMO was NOT_REACHED and raw exception
  text is absent;
- approval/resume success uses an explicitly registered SANDBOX publisher,
  rather than relying on the old fake-success default adapter.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tests" / "test_prod_runtime_01_single_run_authority.py"
text = PATH.read_text(encoding="utf-8")

import_anchor = "from app_api.server import DepartmentAppBackend, GLOBAL_API_SESSION_TOKEN\n"
import_line = "from connectors.publishing_connector import SandboxPublishingConnector\n"
if import_line not in text:
    if text.count(import_anchor) != 1:
        raise RuntimeError("POST3_DRIFT import anchor")
    text = text.replace(import_anchor, import_anchor + import_line)

old_crash = '''        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "FAILED")
        self.assertIn("UNHANDLED_RUNTIME_EXCEPTION", final_cmo.get("reason", ""))
        self.assertNotIn("UNEXPECTED_PIPELINE_CRASH", final_cmo.get("reason", ""))
'''
new_crash = '''        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)
        self.assertEqual(final_cmo.get("status"), "NOT_REACHED")
        self.assertEqual(final_cmo.get("reason"), "RUNTIME_INTERNAL_ERROR")
        self.assertNotIn("UNEXPECTED_PIPELINE_CRASH", str(final_cmo))
        self.assertNotIn("UNEXPECTED_PIPELINE_CRASH", str(ctx.risk_flags))
'''
if text.count(old_crash) != 1:
    raise RuntimeError(f"POST3_DRIFT crash test block={text.count(old_crash)}")
text = text.replace(old_crash, new_crash)

old_resume = '''        rt = _build_test_runtime()
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        item = mgr.enqueue_run(objective="Approval resume queue test", run_id=rid)
'''
new_resume = '''        rt = _build_test_runtime()
        # The generic publishing adapter now fails closed by design.  This test
        # explicitly opts into the real sandbox connector so that it tests
        # approval/resume state rather than accidental fake provider success.
        rt.tool_gateway.bind_adapter_alias("social_publish_adapter", SandboxPublishingConnector())
        mgr = RunManager(runtime=rt, max_workers=0)
        rid = rt.reserve_run_id()
        item = mgr.enqueue_run(objective="Approval resume queue test", run_id=rid)
'''
if text.count(old_resume) != 1:
    raise RuntimeError(f"POST3_DRIFT approval-resume block={text.count(old_resume)}")
text = text.replace(old_resume, new_resume)

PATH.write_text(text, encoding="utf-8")
print("FULL_DEFECT_SWEEP_V2_POST3_TEST_FIXTURES_APPLIED")
