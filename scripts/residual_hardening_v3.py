"""One-shot deterministic residual hardening for phase/full-hardening-v2.

This script exists only to apply reviewed, exact-boundary changes in CI where
large source files are impractical to edit through the Contents API.  Every
replacement is idempotent and fails closed on unexpected source drift.
"""
from __future__ import annotations

from pathlib import Path


changed_files: set[str] = set()


def replace(path: str, old: str, new: str, *, expected: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and new in text:
        return
    if count != expected:
        raise RuntimeError(f"{path}: expected {expected} boundary match(es), found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")
    changed_files.add(path)


def replace_if_present(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old in text:
        p.write_text(text.replace(old, new), encoding="utf-8")
        changed_files.add(path)
    elif new not in text:
        raise RuntimeError(f"{path}: neither old nor new boundary found: {old[:120]!r}")


# ---------------------------------------------------------------------------
# Production: Final CMO may never authorize an explicitly INCONCLUSIVE
# structured Performance evaluation.
# ---------------------------------------------------------------------------
replace(
    "runtime/engine.py",
    '''            has_valid_observed_result = (\n                execution_state == "RESULT_OBSERVED"\n                and eval_status in ("SUPPORTED", "NOT_SUPPORTED")\n                and eval_origin == "REAL"\n            )\n\n            if not has_valid_observed_result:\n''',
    '''            has_valid_observed_result = (\n                execution_state == "RESULT_OBSERVED"\n                and eval_status in ("SUPPORTED", "NOT_SUPPORTED")\n                and eval_origin == "REAL"\n            )\n\n            # An explicit structured INCONCLUSIVE verdict is authoritative.\n            # It is stronger than prose and must block deployment even when\n            # the Performance prose itself omitted an inconclusive marker.\n            if eval_status == "INCONCLUSIVE":\n                blocked += 1\n                claim_actions["performance_evaluation"] = "HOLD"\n                blocking_reasons.append(\n                    "PERFORMANCE_EVALUATION_INCONCLUSIVE: Structured Performance "\n                    "evaluation is INCONCLUSIVE; deployment cannot be authorized."\n                )\n\n            if not has_valid_observed_result:\n''',
)

# ---------------------------------------------------------------------------
# Production: after an approved consequential action fails to execute, the run
# must not remain stuck in WAITING_FOR_APPROVAL.
# ---------------------------------------------------------------------------
replace(
    "runtime/engine.py",
    '''        if receipt.status == ExecutionStatus.APPROVAL_REQUIRED:\n            context.status = RuntimeStatus.WAITING_FOR_APPROVAL\n            context.create_checkpoint(pending_approval_id=receipt.execution_id)\n        elif receipt.status == ExecutionStatus.SUCCESS:\n            context.status = RuntimeStatus.RUNNING\n            context.create_checkpoint()\n\n        return receipt\n''',
    '''        if receipt.status == ExecutionStatus.APPROVAL_REQUIRED:\n            context.status = RuntimeStatus.WAITING_FOR_APPROVAL\n            context.create_checkpoint(pending_approval_id=receipt.execution_id)\n        elif receipt.status == ExecutionStatus.SUCCESS:\n            context.status = RuntimeStatus.RUNNING\n            context.create_checkpoint()\n        elif receipt.status in (ExecutionStatus.ERROR, ExecutionStatus.TIMEOUT, ExecutionStatus.BLOCKED):\n            # Approval is authorization, not proof of execution.  Once an\n            # approved action actually fails, leave WAITING_FOR_APPROVAL and\n            # surface a truthful terminal run state instead of waiting forever.\n            context.status = RuntimeStatus.FAILED\n            context.risk_flags.append(\n                f"PUBLISH_ACTION_FAILED: {receipt.error_class or receipt.status.value}"\n            )\n            context.create_checkpoint()\n\n        return receipt\n''',
)

replace(
    "runtime/queue.py",
    '''                if ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:\n                    item.status = RunQueueStatus.WAITING_APPROVAL\n                elif ctx.status == RuntimeStatus.RUNNING:\n                    item.status = RunQueueStatus.RUNNING\n                elif ctx.status == RuntimeStatus.PAUSED:\n                    item.status = RunQueueStatus.PAUSED\n''',
    '''                if ctx.status == RuntimeStatus.WAITING_FOR_APPROVAL:\n                    item.status = RunQueueStatus.WAITING_APPROVAL\n                elif ctx.status == RuntimeStatus.RUNNING:\n                    item.status = RunQueueStatus.RUNNING\n                elif ctx.status == RuntimeStatus.PAUSED:\n                    item.status = RunQueueStatus.PAUSED\n                elif ctx.status == RuntimeStatus.FAILED:\n                    item.status = RunQueueStatus.FAILED\n                elif ctx.status == RuntimeStatus.CANCELLED:\n                    item.status = RunQueueStatus.CANCELLED\n                elif ctx.status == RuntimeStatus.COMPLETED:\n                    item.status = RunQueueStatus.COMPLETED\n''',
)

# ---------------------------------------------------------------------------
# Production: safe deterministic offline shortcuts are genuine local answers,
# not fake model success.  Use them only for narrow no-document queries.
# ---------------------------------------------------------------------------
replace(
    "chat/engine.py",
    '''        doc_context_str = "\\n\\n".join(doc_context_parts) if doc_context_parts else ""\n\n        # Streaming execution path\n''',
    '''        doc_context_str = "\\n\\n".join(doc_context_parts) if doc_context_parts else ""\n\n        # Narrow deterministic local shortcuts are allowed only when there is\n        # no document-analysis request and no attachment context.  They make no\n        # external-action or research claims and therefore do not masquerade as\n        # provider success.\n        offline_fallback = None\n        if not is_document_analysis and not doc_context_parts:\n            offline_fallback = self._generate_offline_conversational_fallback(user_message, doc_context_str)\n        if offline_fallback is not None:\n            if emitter:\n                emitter.emit(\n                    ProgressEventType.RUN_COMPLETED,\n                    message="Hoàn tất phản hồi hội thoại cục bộ",\n                    metadata={"execution_mode": "DETERMINISTIC_LOCAL"},\n                )\n            return {\n                "success": True,\n                "content": offline_fallback,\n                "provider": "local_deterministic",\n                "model_name": "none",\n                "mode": "GENERAL_CONVERSATION",\n                "execution_mode": "DETERMINISTIC_LOCAL",\n            }\n\n        # Streaming execution path\n''',
)
replace(
    "chat/engine.py",
    '''            return "Xin chào! Tôi là trợ lý AI thuộc phòng Marketing. Tôi có thể giúp bạn trò chuyện, giải đáp thắc mắc, phân tích tài liệu hoặc khởi chạy các chiến dịch tiếp thị khi bạn cần."\n''',
    '''            return "Xin chào! Tôi là trợ lý AI thuộc phòng Marketing. Tôi có thể giúp bạn trò chuyện, giải đáp thắc mắc, phân tích tài liệu và lập kế hoạch marketing. Các hành động bên ngoài chỉ được thực hiện khi có công cụ được kết nối và quyền cho phép phù hợp."\n''',
)

# ---------------------------------------------------------------------------
# Regression alignment: privacy-safe TypeError boundary.
# ---------------------------------------------------------------------------
replace_if_present(
    "tests/test_prod_runtime_progress_01.py",
    '        self.assertIn("TypeErrorModelGateway", err)\n',
    '        self.assertEqual(err, "RUNTIME_INTERNAL_ERROR")\n        self.assertNotIn("TypeErrorModelGateway", err)\n',
)
replace(
    "tests/test_prod_core_authority_01a.py",
    '        self.assertIn("TypeErrorGateway", err)\n',
    '        self.assertEqual(err, "RUNTIME_INTERNAL_ERROR")\n        self.assertNotIn("TypeErrorGateway", err)\n',
    expected=2,
)

# Performance failure now short-circuits Final CMO rather than synthesizing over
# a broken upstream stage.
replace(
    "tests/test_prod_core_authority_01a.py",
    '''    def test_P_performance_failure_stops_final_cmo(self) -> None:\n        """If Performance fails, Final CMO still runs (governed synthesis per contract)."""\n        gw = MockScriptedGateway(fail_stage="performance")\n        rt = _build_runtime(gateway=gw)\n\n        final_cmo_called = [False]\n        orig_final = rt.execute_stage_final_cmo\n        def tracked_final(ctx):\n            final_cmo_called[0] = True\n            return orig_final(ctx)\n        rt.execute_stage_final_cmo = tracked_final\n\n        ctx, final_out, _ = rt.run_workflow(\n            objective="Fail at performance", business_id="BIZ_001"\n        )\n\n        # Final CMO is governed and always runs per the canonical contract\n        self.assertTrue(final_cmo_called[0])\n''',
    '''    def test_P_performance_failure_stops_final_cmo(self) -> None:\n        """If Performance fails, Final CMO is NOT_REACHED and never executes."""\n        gw = MockScriptedGateway(fail_stage="performance")\n        rt = _build_runtime(gateway=gw)\n\n        final_cmo_called = [False]\n        orig_final = rt.execute_stage_final_cmo\n        def tracked_final(ctx):\n            final_cmo_called[0] = True\n            return orig_final(ctx)\n        rt.execute_stage_final_cmo = tracked_final\n\n        ctx, final_out, _ = rt.run_workflow(\n            objective="Fail at performance", business_id="BIZ_001"\n        )\n\n        self.assertFalse(final_cmo_called[0])\n        self.assertEqual(ctx.status, RuntimeStatus.FAILED)\n        self.assertEqual(final_out.get("status"), "NOT_REACHED")\n        self.assertEqual(final_out.get("failed_stage"), "PERFORMANCE")\n        self.assertNotIn("PREVIOUS_STAGE_FAILED", str(final_out))\n''',
)

# Typed progress events are objects, not dictionaries.
replace(
    "tests/test_prod_workflow_failure_semantics_01.py",
    'e.get("stage") == "FINAL_CMO" and e.get("event_type") == "STAGE_STARTED"',
    'getattr(e, "stage", None) == "FINAL_CMO" and getattr(e, "event_type", None) == "STAGE_STARTED"',
    expected=2,
)

# Approval does not manufacture a publishing connector or successful side effect.
replace(
    "tests/test_prod_runtime_01_single_run_authority.py",
    '''    def test_41_queue_approval_resume_returns_to_running(self) -> None:\n        """After approval is registered and run resumed, queue item returns to RUNNING."""\n''',
    '''    def test_41_queue_approval_resume_returns_to_running(self) -> None:\n        """Approval authorizes execution but a missing real publisher fails truthfully."""\n''',
)
replace(
    "tests/test_prod_runtime_01_single_run_authority.py",
    '''        # Resume action\n        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token=appr_rec.approval_token)\n        self.assertEqual(rec.status, ExecutionStatus.SUCCESS)\n        self.assertEqual(ctx.status, RuntimeStatus.RUNNING)\n        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.RUNNING)\n        mgr._stop_event.set()\n''',
    '''        # Approval is only authorization.  The default publisher has no\n        # real connector, so execution must fail closed rather than fake success.\n        rec = rt.request_publish_action(ctx, platform="linkedin", approval_token=appr_rec.approval_token)\n        self.assertEqual(rec.status, ExecutionStatus.ERROR)\n        self.assertEqual(ctx.status, RuntimeStatus.FAILED)\n        self.assertEqual(mgr.get_run(rid).status, RunQueueStatus.FAILED)\n        mgr._stop_event.set()\n''',
)

# Truth tests: deterministic arithmetic from explicit inputs is a real local
# computation; absent attribution/experiment data must fail closed.
replace(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '        self.assertEqual(receipt_valid.execution_mode, ExecutionMode.MOCK)\n',
    '        self.assertEqual(receipt_valid.execution_mode, ExecutionMode.REAL)\n',
)
replace(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''        self.assertEqual(rec_attr.status, ExecutionStatus.SUCCESS)\n        self.assertEqual(rec_attr.execution_mode, ExecutionMode.MOCK)\n        self.assertNotEqual(rec_attr.execution_mode, ExecutionMode.REAL)\n\n        req_stat = ToolRequest(agent_id="performance", capability_id="experiment_result_analysis", parameters={})\n        rec_stat = self.tool_gateway.execute(req_stat)\n        self.assertEqual(rec_stat.status, ExecutionStatus.SUCCESS)\n        self.assertEqual(rec_stat.execution_mode, ExecutionMode.MOCK)\n        self.assertNotEqual(rec_stat.execution_mode, ExecutionMode.REAL)\n''',
    '''        self.assertEqual(rec_attr.status, ExecutionStatus.ERROR)\n        self.assertNotEqual(rec_attr.execution_mode, ExecutionMode.REAL)\n        self.assertIsNone(rec_attr.data)\n\n        req_stat = ToolRequest(agent_id="performance", capability_id="experiment_result_analysis", parameters={})\n        rec_stat = self.tool_gateway.execute(req_stat)\n        self.assertEqual(rec_stat.status, ExecutionStatus.ERROR)\n        self.assertNotEqual(rec_stat.execution_mode, ExecutionMode.REAL)\n        self.assertIsNone(rec_stat.data)\n''',
)

# Legacy SearchAdapter may remain importable, but must not fabricate example.com
# evidence or return a successful mock research result.
replace(
    "tests/test_prod_research_evidence_01a.py",
    '''    def test_old_search_adapter_returns_mock(self) -> None:\n        """The original SearchAdapter still returns MOCK (for backward compat in tests)."""\n        adapter = SearchAdapter()\n        result = adapter.execute("web_search", {"query": "test"})\n        self.assertTrue(result.success)\n        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)\n        self.assertIn("example.com", str(result.data))\n''',
    '''    def test_old_search_adapter_returns_mock(self) -> None:\n        """Legacy SearchAdapter fails closed and never fabricates research evidence."""\n        adapter = SearchAdapter()\n        result = adapter.execute("web_search", {"query": "test"})\n        self.assertFalse(result.success)\n        self.assertEqual(result.execution_mode, ExecutionMode.MOCK)\n        self.assertNotIn("example.com", str(result.data))\n''',
)
replace(
    "tests/test_prod_research_evidence_01a.py",
    '''        old = SearchAdapter()\n        old_result = old.execute("web_search", {"query": "test"})\n        self.assertIn("example.com", str(old_result.data))\n''',
    '''        old = SearchAdapter()\n        old_result = old.execute("web_search", {"query": "test"})\n        self.assertFalse(old_result.success)\n        self.assertNotIn("example.com", str(old_result.data))\n''',
)

# Creative asset lineage is retained even when no real renderer is bound.
replace(
    "tests/test_creative_performance_true_handoff.py",
    '''        self.assertEqual(assets[0]["status"], "SUCCESS")\n        self.assertIn(assets[0]["execution_mode"], ("REAL", "MOCK", "SANDBOX"))\n''',
    '''        self.assertEqual(assets[0]["status"], "ERROR")\n        self.assertNotEqual(assets[0]["execution_mode"], "REAL")\n''',
)

# ---------------------------------------------------------------------------
# Model-settings suite: keep production SecureSecretStore fail-closed on Linux.
# Cross-platform behavior tests explicitly use the in-memory DI store; genuine
# DPAPI/ciphertext tests are Windows-only.
# ---------------------------------------------------------------------------
model_test = "tests/test_prod_model_settings_01.py"
for test_name in (
    "test_41_windows_dpapi_failure_fails_closed",
    "test_43_vault_corruption_fails_closed",
    "test_44_plaintext_sentinel_absent_from_persisted_files",
    "test_87_zero_byte_existing_vault_fails_closed",
    "test_88_malformed_encrypted_vault_fails_closed",
    "test_89_corrupt_vault_preserved_after_failed_operation",
):
    replace_if_present(
        model_test,
        f"    def {test_name}(self):\n",
        f"    @unittest.skipUnless(sys.platform == \"win32\", \"Windows DPAPI/vault contract\")\n    def {test_name}(self):\n",
    )

store_replacements = {
    '        probe_store = SecureSecretStore(vault_path=td_vault)\n':
        '        probe_store = SecureSecretStore(vault_path=td_vault) if sys.platform == "win32" else InMemorySecretStore()\n',
    '        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"alias_{order_run1_first}.vault")\n':
        '        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"alias_{order_run1_first}.vault") if sys.platform == "win32" else InMemorySecretStore()\n',
    '        vault = SecureSecretStore(vault_path=Path(self.test_dir) / "evict.vault")\n':
        '        vault = SecureSecretStore(vault_path=Path(self.test_dir) / "evict.vault") if sys.platform == "win32" else InMemorySecretStore()\n',
    '        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"rb_{id(self)}.vault")\n':
        '        store = SecureSecretStore(vault_path=Path(self.test_dir) / f"rb_{id(self)}.vault") if sys.platform == "win32" else InMemorySecretStore()\n',
    '            store = SecureSecretStore(vault_path=Path(self.test_dir) / "fb.vault")\n':
        '            store = SecureSecretStore(vault_path=Path(self.test_dir) / "fb.vault") if sys.platform == "win32" else InMemorySecretStore()\n',
    '        store = SecureSecretStore(vault_path=Path(self.test_dir) / "allblock.vault")\n':
        '        store = SecureSecretStore(vault_path=Path(self.test_dir) / "allblock.vault") if sys.platform == "win32" else InMemorySecretStore()\n',
}
for old, new in store_replacements.items():
    replace_if_present(model_test, old, new)

print("Residual hardening changed:", ", ".join(sorted(changed_files)) or "none")
