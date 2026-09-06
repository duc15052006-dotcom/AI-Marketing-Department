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

start_marker = "        # Invoke ToolGateway for search observation\n"
end_marker = (
    '        grounded_pkg = self.context_compiler.compile_grounded_package('
    '"intelligence", context, tool_receipts=[search_receipt])\n'
)
if text.count(start_marker) != 1:
    raise SystemExit(f"SEARCH_START_ANCHOR_MISMATCH: {text.count(start_marker)}")
if text.count(end_marker) != 1:
    raise SystemExit(f"SEARCH_END_ANCHOR_MISMATCH: {text.count(end_marker)}")
start = text.index(start_marker)
end = text.index(end_marker, start) + len(end_marker)

new_block = '''        # Runtime-owned research decomposition. These acquisition tasks have
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
        # Preserve the first (market) receipt as the canonical primary receipt
        # for the existing single-observation quality contract. Generic grounded
        # context and audit lineage consume all three receipts.
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

        # Deterministic merge boundary: only after the wave joins do all
        # receipts enter the shared grounded context.
        grounded_pkg = self.context_compiler.compile_grounded_package(
            "intelligence", context, tool_receipts=research_receipts
        )
'''

text = text[:start] + new_block + text[end:]
path.write_text(text, encoding="utf-8")
