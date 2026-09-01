from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}\n--- OLD ---\n{old}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched {path}")


# ---------------------------------------------------------------------------
# Phase 1B fixtures: bind synthetic receipts to the same immutable runtime
# scope they are intended to exercise. Assertions remain unchanged.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_phase1b_grounded_context.py",
    '''                return ExecutionReceipt(\n                    execution_id="EXEC-SEARCH-9182",\n                    run_id="RUN-TEST-F",\n                    agent_id="intelligence",\n                    capability_id="web_search",\n                    provider="mock_search",\n                    request_hash="mock_hash_f",\n                    status=ExecutionStatus.SUCCESS,\n                    execution_mode=ExecutionMode.MOCK,\n                    output={"query": req.parameters.get("query"), "result": "Competitor landscape: TOOL_EVIDENCE_MARKER_9182"},\n                )''',
    '''                return ExecutionReceipt(\n                    execution_id="EXEC-SEARCH-9182",\n                    run_id=req.run_id,\n                    agent_id="intelligence",\n                    capability_id="web_search",\n                    provider="mock_search",\n                    request_hash="mock_hash_f",\n                    status=ExecutionStatus.SUCCESS,\n                    execution_mode=ExecutionMode.MOCK,\n                    business_id=req.business_id,\n                    project_id=req.project_id,\n                    chat_id=req.chat_id,\n                    output={"query": req.parameters.get("query"), "result": "Competitor landscape: TOOL_EVIDENCE_MARKER_9182"},\n                )''',
)

replace_once(
    "tests/test_phase1b_grounded_context.py",
    '''        receipt = ExecutionReceipt(\n            execution_id="EXEC-EMPTY-001",\n            run_id="RUN-TEST-G",\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="mock_search",\n            request_hash="mock_hash_g",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK,\n            output="",\n        )\n        ctx = self.runtime.start_run(objective="Explore market")''',
    '''        ctx = self.runtime.start_run(objective="Explore market")\n        receipt = ExecutionReceipt(\n            execution_id="EXEC-EMPTY-001",\n            run_id=ctx.run_id,\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="mock_search",\n            request_hash="mock_hash_g",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK,\n            business_id=ctx.business_id,\n            project_id=ctx.project_id,\n            chat_id=ctx.chat_id,\n            output="",\n        )''',
)

replace_once(
    "tests/test_phase1b_grounded_context.py",
    '''        mock_receipt = ExecutionReceipt(\n            execution_id="EXEC-MOCK-SUCCESS",\n            run_id="RUN-TEST-MOCK",\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="mock_search",\n            request_hash="mock_hash_success",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK,\n            output={"claim": "MARKET_SHARE_IS_92_PERCENT"},\n        )\n        ctx = self.runtime.start_run(objective="Assess market share")''',
    '''        ctx = self.runtime.start_run(objective="Assess market share")\n        mock_receipt = ExecutionReceipt(\n            execution_id="EXEC-MOCK-SUCCESS",\n            run_id=ctx.run_id,\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="mock_search",\n            request_hash="mock_hash_success",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK,\n            business_id=ctx.business_id,\n            project_id=ctx.project_id,\n            chat_id=ctx.chat_id,\n            output={"claim": "MARKET_SHARE_IS_92_PERCENT"},\n        )''',
)

replace_once(
    "tests/test_phase1b_grounded_context.py",
    '''        receipt = ExecutionReceipt(\n            run_id="RUN-REAL-TOOL",\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="google_search",\n            request_hash="hash123",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.REAL,\n            output={"content": "MARKET_SHARE_IS_92_PERCENT"},\n        )\n        ctx = RuntimeContext(objective="Find market share for CRM", business_id="BIZ_TEST")''',
    '''        ctx = RuntimeContext(objective="Find market share for CRM", business_id="BIZ_TEST")\n        receipt = ExecutionReceipt(\n            run_id=ctx.run_id,\n            agent_id="intelligence",\n            capability_id="web_search",\n            provider="google_search",\n            request_hash="hash123",\n            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.REAL,\n            business_id=ctx.business_id,\n            project_id=ctx.project_id,\n            chat_id=ctx.chat_id,\n            output={"content": "MARKET_SHARE_IS_92_PERCENT"},\n        )''',
)

# ---------------------------------------------------------------------------
# Collaboration audit: same-run private-business fixture must carry business
# authority so the epistemic-tier assertion is not false-green via scope reject.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_collaboration_integrity_audit.py",
    '''        mock_receipt = ExecutionReceipt(\n            run_id=ctx.run_id, agent_id="intelligence", capability_id="web_search",\n            provider="mock_provider", request_hash="h", status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK, output={"results": ["simulated snippet"]},\n        )''',
    '''        mock_receipt = ExecutionReceipt(\n            run_id=ctx.run_id, agent_id="intelligence", capability_id="web_search",\n            provider="mock_provider", request_hash="h", status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.MOCK, business_id=ctx.business_id,\n            project_id=ctx.project_id, chat_id=ctx.chat_id,\n            output={"results": ["simulated snippet"]},\n        )''',
)

# ---------------------------------------------------------------------------
# PROD-TRUTH fixtures: keep exact run/tenant scope when testing receipt payload
# and EvidenceRole behavior. This strengthens the tests rather than weakening
# the production matcher.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            status=ExecutionStatus.SUCCESS,\n            data={"query": "battery tech", "findings": "Solid state advancement"},\n            output=None,\n        )\n        ctx = RuntimeContext(run_id="RUN-TEST-11", objective="Battery research", business_id="BIZ_TECH")''',
    '''            status=ExecutionStatus.SUCCESS,\n            business_id="BIZ_TECH",\n            data={"query": "battery tech", "findings": "Solid state advancement"},\n            output=None,\n        )\n        ctx = RuntimeContext(run_id="RUN-TEST-11", objective="Battery research", business_id="BIZ_TECH")''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            execution_mode=ExecutionMode.REAL,\n            status=ExecutionStatus.SUCCESS,\n            data={"content": "Verified payload"},\n        )\n        ctx = RuntimeContext(run_id="RUN-TEST-17", objective="Metadata test", business_id="BIZ_META")''',
    '''            execution_mode=ExecutionMode.REAL,\n            status=ExecutionStatus.SUCCESS,\n            business_id="BIZ_META",\n            data={"content": "Verified payload"},\n        )\n        ctx = RuntimeContext(run_id="RUN-TEST-17", objective="Metadata test", business_id="BIZ_META")''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])\n\n            # Setup file on disk\n            req_write = ToolRequest(\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "market_notes.txt", "content": "Organic search traffic grew 35% MoM."},\n            )''',
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])\n            ctx = RuntimeContext(run_id="RUN-FILE-READ", objective="File observation")\n\n            # Setup file on disk\n            req_write = ToolRequest(\n                run_id=ctx.run_id,\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "market_notes.txt", "content": "Organic search traffic grew 35% MoM."},\n                business_id=ctx.business_id,\n                project_id=ctx.project_id,\n                chat_id=ctx.chat_id,\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            req_read = ToolRequest(\n                agent_id="intelligence",\n                capability_id="file_read",\n                parameters={"path": "market_notes.txt"},\n            )''',
    '''            req_read = ToolRequest(\n                run_id=ctx.run_id,\n                agent_id="intelligence",\n                capability_id="file_read",\n                parameters={"path": "market_notes.txt"},\n                business_id=ctx.business_id,\n                project_id=ctx.project_id,\n                chat_id=ctx.chat_id,\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            # Compile into GroundedContextPackage\n            ctx = RuntimeContext(run_id="RUN-FILE-READ", objective="File observation")\n            pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[rec_read])''',
    '''            # Compile into GroundedContextPackage\n            pkg = self.compiler.compile_grounded_package("intelligence", ctx, tool_receipts=[rec_read])''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter", "db_storage_adapter"])\n\n            # Seed a JSON record\n            req_write = ToolRequest(\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "metrics.json", "content": '{"customer_retention_rate": 0.88}'},\n            )''',
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter", "db_storage_adapter"])\n            ctx = RuntimeContext(run_id="RUN-DB-QUERY", objective="Storage query")\n\n            # Seed a JSON record\n            req_write = ToolRequest(\n                run_id=ctx.run_id,\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "metrics.json", "content": '{"customer_retention_rate": 0.88}'},\n                business_id=ctx.business_id,\n                project_id=ctx.project_id,\n                chat_id=ctx.chat_id,\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            req_query = ToolRequest(\n                agent_id="performance",\n                capability_id="structured_storage_query",\n                parameters={"path": "metrics.json"},\n            )''',
    '''            req_query = ToolRequest(\n                run_id=ctx.run_id,\n                agent_id="performance",\n                capability_id="structured_storage_query",\n                parameters={"path": "metrics.json"},\n                business_id=ctx.business_id,\n                project_id=ctx.project_id,\n                chat_id=ctx.chat_id,\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            ctx = RuntimeContext(run_id="RUN-DB-QUERY", objective="Storage query")\n            pkg = self.compiler.compile_grounded_package("performance", ctx, tool_receipts=[rec_query])''',
    '''            pkg = self.compiler.compile_grounded_package("performance", ctx, tool_receipts=[rec_query])''',
)

# Strengthen file_write ACTION test so zero evidence is due EvidenceRole.ACTION,
# not an unrelated foreign-run rejection.
replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])\n\n            req_write = ToolRequest(\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "output.txt", "content": "Generated campaign draft."},\n            )''',
    '''            self.tool_gateway.register_adapter(file_conn, aliases=["file_io_adapter"])\n            ctx = RuntimeContext(run_id="RUN-WRITE-01", objective="Write test")\n\n            req_write = ToolRequest(\n                run_id=ctx.run_id,\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "output.txt", "content": "Generated campaign draft."},\n                business_id=ctx.business_id,\n                project_id=ctx.project_id,\n                chat_id=ctx.chat_id,\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            # Compile through ContextCompiler\n            ctx = RuntimeContext(run_id="RUN-WRITE-01", objective="Write test")\n            pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[rec_write])''',
    '''            # Compile through ContextCompiler\n            pkg = self.compiler.compile_grounded_package("cmo", ctx, tool_receipts=[rec_write])''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            req_write = ToolRequest(\n                run_id="RUN-CLAIM-TEST",\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "spec.txt", "content": "Hardware test spec: Device features 5000mAh battery."},\n            )''',
    '''            req_write = ToolRequest(\n                run_id="RUN-CLAIM-TEST",\n                agent_id="cmo",\n                capability_id="file_write",\n                parameters={"path": "spec.txt", "content": "Hardware test spec: Device features 5000mAh battery."},\n                business_id="BIZ_TEST",\n            )''',
)

replace_once(
    "tests/test_prod_truth_01_execution_truthfulness.py",
    '''            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.REAL,\n            data={"post_id": "POST-12345", "status": "LIVE"},\n        )''',
    '''            status=ExecutionStatus.SUCCESS,\n            execution_mode=ExecutionMode.REAL,\n            business_id="BIZ_TEST",\n            data={"post_id": "POST-12345", "status": "LIVE"},\n        )''',
)

# ---------------------------------------------------------------------------
# Lock the fail-closed compatibility decision into the adversarial test:
# private runtime scope + missing business metadata must be rejected.
# ---------------------------------------------------------------------------
replace_once(
    "tests/test_tool_receipt_runtime_scope_binding_v1.py",
    '''            self._receipt(run_id="RUN-SCOPE-B", marker="FOREIGN-RUN"),\n            self._receipt(business_id="BIZ_B", marker="FOREIGN-BUSINESS"),\n            self._receipt(project_id="PROJ_B", marker="FOREIGN-PROJECT"),\n            self._receipt(chat_id="CHAT_B", marker="FOREIGN-CHAT"),''',
    '''            self._receipt(run_id="RUN-SCOPE-B", marker="FOREIGN-RUN"),\n            self._receipt(business_id="BIZ_B", marker="FOREIGN-BUSINESS"),\n            self._receipt(business_id=None, marker="MISSING-BUSINESS"),\n            self._receipt(project_id="PROJ_B", marker="FOREIGN-PROJECT"),\n            self._receipt(chat_id="CHAT_B", marker="FOREIGN-CHAT"),''',
)

print("PR98 fixture repair complete")
