from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")

import_old = "from runtime.context_compiler import ContextCompiler\nfrom runtime.handoff import (\n"
import_new = (
    "from runtime.context_compiler import ContextCompiler\n"
    "from runtime.dependency_scheduler import DependencyAwareScheduler, RuntimeTaskSpec\n"
    "from runtime.handoff import (\n"
)
if text.count(import_old) != 1:
    raise SystemExit("IMPORT_ANCHOR_MISMATCH")
text = text.replace(import_old, import_new, 1)

old = '''        # Invoke ToolGateway for search observation
        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_STARTED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Bắt đầu tìm kiếm dữ liệu thị trường qua ToolGateway",
                metadata={"capability": "web_search"},
            )

        idem_key = f"{context.run_id}:intelligence:web_search:{context.objective}"
        search_req = ToolRequest(
            run_id=context.run_id,
            agent_id="intelligence",
            capability_id="web_search",
            parameters={"query": context.objective},
            business_id=context.business_id,
            project_id=context.project_id,
            chat_id=context.chat_id,
        )
        search_receipt = self._execute_tool_singleflight(idem_key, search_req)

        context.execution_receipt_refs.append(search_receipt.execution_id)
        self.lineage_inspector.add_receipt(search_receipt)

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Hoàn tất tìm kiếm dữ liệu thị trường",
                metadata={"execution_id": search_receipt.execution_id, "status": search_receipt.status.value},
            )

        # Grounded Context Compilation with actual Tool Receipt content
        grounded_pkg = self.context_compiler.compile_grounded_package("intelligence", context, tool_receipts=[search_receipt])
'''

new = '''        # Runtime-owned research decomposition. These acquisition tasks have
        # known, isolated write scopes, so the dependency scheduler may execute
        # them in one parallel wave. Worker threads return receipts only; all
        # RuntimeContext and lineage mutation stays on this caller thread.
        research_tasks = (
            RuntimeTaskSpec(
                task_id="intelligence-market",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.market"}),
                task_kind="intelligence.market",
                instruction=f"{context.objective} market landscape trends demand",
            ),
            RuntimeTaskSpec(
                task_id="intelligence-competitors",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.competitors"}),
                task_kind="intelligence.competitors",
                instruction=f"{context.objective} competitors alternatives benchmarks",
            ),
            RuntimeTaskSpec(
                task_id="intelligence-customers",
                agent_id="intelligence",
                reads=frozenset({"objective", "grounded_context"}),
                writes=frozenset({"isolated.intelligence.customers"}),
                task_kind="intelligence.customers",
                instruction=f"{context.objective} customer motivations pain points objections",
            ),
        )
        research_scheduler = DependencyAwareScheduler(max_workers=3)
        research_plan = research_scheduler.plan(research_tasks)

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_STARTED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Bắt đầu tìm kiếm dữ liệu Intelligence theo kế hoạch phụ thuộc",
                metadata={
                    "capability": "web_search",
                    "task_ids": [task.task_id for task in research_tasks],
                    "waves": [list(wave) for wave in research_plan.waves],
                },
            )

        def run_research_task(task: RuntimeTaskSpec) -> ExecutionReceipt:
            query = task.instruction
            query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
            idem_key = f"{context.run_id}:intelligence:web_search:{task.task_id}:{query_hash}"
            search_req = ToolRequest(
                run_id=context.run_id,
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": query},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            return self._execute_tool_singleflight(idem_key, search_req)

        research_results = research_scheduler.execute(research_tasks, run_research_task)
        research_receipts = [research_results[task.task_id] for task in research_tasks]
        # The market receipt remains the canonical primary receipt for the
        # existing single-observation research-quality contract. All receipts
        # are still delivered to generic grounded context and audit lineage.
        search_receipt = research_receipts[0]

        for receipt in research_receipts:
            context.execution_receipt_refs.append(receipt.execution_id)
            self.lineage_inspector.add_receipt(receipt)

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Hoàn tất các nhánh tìm kiếm Intelligence độc lập",
                metadata={
                    "execution_ids": [receipt.execution_id for receipt in research_receipts],
                    "statuses": [receipt.status.value for receipt in research_receipts],
                    "task_count": len(research_tasks),
                    "wave_count": len(research_plan.waves),
                },
            )

        # Grounded Context Compilation consumes every isolated research receipt
        # after deterministic caller-thread merge.
        grounded_pkg = self.context_compiler.compile_grounded_package(
            "intelligence", context, tool_receipts=research_receipts
        )
'''

if text.count(old) != 1:
    raise SystemExit(f"INTELLIGENCE_SEARCH_ANCHOR_MISMATCH: {text.count(old)}")
text = text.replace(old, new, 1)

failure_receipt_anchor = '                "search_receipt_id": search_receipt.execution_id,\n'
if text.count(failure_receipt_anchor) != 2:
    raise SystemExit(f"FAILED_RECEIPT_OUTPUT_ANCHOR_MISMATCH: {text.count(failure_receipt_anchor)}")
text = text.replace(
    failure_receipt_anchor,
    failure_receipt_anchor + '                "search_receipt_ids": [receipt.execution_id for receipt in research_receipts],\n',
)

completed_receipt_anchor = '            "search_receipt_id": search_receipt.execution_id,\n'
if text.count(completed_receipt_anchor) != 1:
    raise SystemExit(f"COMPLETED_RECEIPT_OUTPUT_ANCHOR_MISMATCH: {text.count(completed_receipt_anchor)}")
text = text.replace(
    completed_receipt_anchor,
    completed_receipt_anchor + '            "search_receipt_ids": [receipt.execution_id for receipt in research_receipts],\n',
    1,
)

path.write_text(text, encoding="utf-8")
