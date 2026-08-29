"""Asserted one-shot migration for the V2 full defect sweep.

Every replacement is count-checked.  If upstream source drifts, CI stops rather
than partially applying an unsafe patch.  This file is deleted after the batch
is certified.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str, count: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"PATCH_ASSERTION_FAILED {path}: expected {count}, found {found}: {old[:100]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime: integrate bounded research through the EXISTING ToolGateway.
# ---------------------------------------------------------------------------
replace_exact(
    "runtime/engine.py",
    "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\n",
    "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\nfrom runtime.research_loop import BoundedResearchLoop\n",
)
replace_exact(
    "runtime/engine.py",
    "        self.lineage_inspector = LineageInspector()\n\n        self._lock = threading.Lock()\n",
    "        self.lineage_inspector = LineageInspector()\n        self.research_loop = BoundedResearchLoop(self.tool_gateway)\n\n        self._lock = threading.Lock()\n",
)
old_search = '''        idem_key = f"{context.run_id}:intelligence:web_search:{context.objective}"
        if idem_key in self._executed_tool_idempotency_keys:
            search_receipt = self._executed_tool_idempotency_keys[idem_key]
        else:
            search_req = ToolRequest(
                run_id=context.run_id,
                agent_id="intelligence",
                capability_id="web_search",
                parameters={"query": context.objective},
                business_id=context.business_id,
                project_id=context.project_id,
                chat_id=context.chat_id,
            )
            search_receipt = self.tool_gateway.execute(search_req)
            self._executed_tool_idempotency_keys[idem_key] = search_receipt

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
new_search = '''        research_depth = str(context.working_state.get("research_depth") or "STANDARD").upper()
        research_execution = self.research_loop.execute(
            run_id=context.run_id,
            agent_id="intelligence",
            objective=context.objective,
            business_id=context.business_id,
            project_id=context.project_id,
            chat_id=context.chat_id,
            depth=research_depth,
        )
        search_receipt = research_execution.search_receipts[0]
        all_research_receipts = research_execution.all_receipts
        for receipt in all_research_receipts:
            context.execution_receipt_refs.append(receipt.execution_id)
            self.lineage_inspector.add_receipt(receipt)
            self._executed_tool_idempotency_keys[f"{context.run_id}:research:{receipt.execution_id}"] = receipt

        context.working_state["research_depth"] = research_execution.plan.depth
        context.working_state["research_query_count"] = len(research_execution.search_receipts)
        context.working_state["research_source_url_count"] = len(research_execution.source_urls)
        context.working_state["research_real_page_count"] = research_execution.real_page_count
        context.working_state["research_backend_errors"] = list(research_execution.backend_errors)
        research_source_section = research_execution.render_page_context()

        if emitter:
            emitter.emit(
                ProgressEventType.RESEARCH_SEARCH_COMPLETED,
                stage="INTELLIGENCE",
                agent="INTELLIGENCE",
                message="Hoàn tất tìm kiếm và đọc nguồn nghiên cứu",
                metadata={
                    "search_count": len(research_execution.search_receipts),
                    "source_url_count": len(research_execution.source_urls),
                    "real_page_count": research_execution.real_page_count,
                    "depth": research_execution.plan.depth,
                },
            )

        # Grounded Context Compilation with all actual research receipts.
        grounded_pkg = self.context_compiler.compile_grounded_package("intelligence", context, tool_receipts=all_research_receipts)
'''
replace_exact("runtime/engine.py", old_search, new_search)
replace_exact(
    "runtime/engine.py",
    '''        if research_grounding_section:
            prompt_parts.append(research_grounding_section)
        prompt_parts.append(evidence_section)
''',
    '''        if research_grounding_section:
            prompt_parts.append(research_grounding_section)
        if research_source_section:
            prompt_parts.append(research_source_section)
        else:
            prompt_parts.append(
                "SOURCE-READ STATUS: No REAL source page was successfully read. "
                "Do not present search snippets as verified high-impact facts; explicitly report evidence gaps."
            )
        prompt_parts.append(evidence_section)
''',
)
replace_exact(
    "runtime/engine.py",
    '''        text_delta_sink: Optional[Callable[[str], None]] = None,
    ) -> Tuple[RuntimeContext, Dict[str, Any], DepartmentRunArtifact]:
        """Research-only fast path: Intelligence stage only, no full workflow.
''',
    '''        text_delta_sink: Optional[Callable[[str], None]] = None,
        research_depth: str = "STANDARD",
    ) -> Tuple[RuntimeContext, Dict[str, Any], DepartmentRunArtifact]:
        """Research-only fast path: Intelligence stage only, no full workflow.
''',
)
replace_exact(
    "runtime/engine.py",
    '''        emitter = self._get_emitter(context)
        if emitter:
''',
    '''        depth_norm = str(research_depth or "STANDARD").upper()
        context.working_state["research_depth"] = depth_norm if depth_norm in {"QUICK", "STANDARD", "DEEP"} else "STANDARD"

        emitter = self._get_emitter(context)
        if emitter:
''',
    count=1,
)
# Never persist arbitrary exception strings in run risk state.
replace_exact(
    "runtime/engine.py",
    '''                logger.exception(f"Unhandled exception during run {context.run_id}: {exc}")
                context.status = RuntimeStatus.FAILED
                context.risk_flags.append(f"UNHANDLED_RUNTIME_EXCEPTION: {str(exc)}")
''',
    '''                logger.error("Unhandled runtime exception for run %s: %s", context.run_id, type(exc).__name__)
                context.status = RuntimeStatus.FAILED
                context.risk_flags.append("UNHANDLED_RUNTIME_EXCEPTION")
''',
)

# ---------------------------------------------------------------------------
# Server: carry resolved research depth into both streaming and sync runtime.
# ---------------------------------------------------------------------------
replace_exact(
    "app_api/server.py",
    '''                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                    )
''',
    '''                        progress_sink=bridge.send_progress,
                        text_delta_sink=bridge.send_delta,
                        research_depth=resolved_followup.research_depth.value,
                    )
''',
    count=1,
)
replace_exact(
    "app_api/server.py",
    '''                    project_id=session.optional_project_id,
                )

                is_failed = intel_out.get("status") == "FAILED"
''',
    '''                    project_id=session.optional_project_id,
                    research_depth=resolved_followup.research_depth.value,
                )

                is_failed = intel_out.get("status") == "FAILED"
''',
    count=1,
)

# ---------------------------------------------------------------------------
# Direct chat: don't remove repeated prior messages; don't overclaim actions.
# ---------------------------------------------------------------------------
replace_exact(
    "chat/engine.py",
    '''        history_msgs = [m for m in session.messages if m.content != user_message]
        recent_history = history_msgs[-8:]
''',
    '''        history_msgs = list(session.messages)
        if history_msgs and history_msgs[-1].role == ChatRole.USER and history_msgs[-1].content == user_message:
            history_msgs = history_msgs[:-1]
        recent_history = history_msgs[-8:]
''',
)
replace_exact(
    "chat/engine.py",
    'return "Xin chào! Tôi là trợ lý AI thuộc phòng Marketing. Tôi có thể giúp bạn trò chuyện, giải đáp thắc mắc, phân tích tài liệu hoặc khởi chạy các chiến dịch tiếp thị khi bạn cần."',
    'return "Xin chào! Tôi là trợ lý AI thuộc phòng Marketing. Tôi có thể giúp bạn trò chuyện, phân tích tài liệu, nghiên cứu và lập kế hoạch marketing. Hành động trên hệ thống bên ngoài chỉ được thực hiện khi có công cụ thật và quyền phù hợp."',
)

# ---------------------------------------------------------------------------
# ToolGateway: no arbitrary exception text in receipts.
# ---------------------------------------------------------------------------
replace_exact(
    "tools/tool_gateway.py",
    '''            err_code = adapter_res.error_code if adapter_res else "EXECUTION_EXCEPTION"
            err_msg = adapter_res.error_message if adapter_res else str(last_exc)
''',
    '''            err_code = adapter_res.error_code if adapter_res else "EXECUTION_EXCEPTION"
            if adapter_res:
                err_msg = adapter_res.error_message
            else:
                if last_exc is not None:
                    logger.warning("Tool adapter exception type: %s", type(last_exc).__name__)
                err_msg = "Adapter execution failed unexpectedly."
''',
)

# ---------------------------------------------------------------------------
# Cost truth: exact model metadata outranks provider-wide assumptions. Unknown
# models fail closed under FREE_ONLY_MODE.
# ---------------------------------------------------------------------------
replace_exact(
    "integrations/models/registry.py",
    "    cost_tier: CostPolicy = CostPolicy.FREE_TIER_ALLOWED\n",
    "    cost_tier: CostPolicy = CostPolicy.UNKNOWN\n",
)
replace_exact(
    "integrations/models/registry.py",
    "    cost_policy: CostPolicy = CostPolicy.FREE_TIER_ALLOWED\n",
    "    cost_policy: CostPolicy = CostPolicy.UNKNOWN\n",
    count=1,
)
replace_exact(
    "integrations/models/gateway.py",
    '''            # ProviderDefinition-declared cost policy is authoritative when a
            # definition exists (including explicit UNKNOWN = unverified);
            # model metadata is only a fallback for undefined providers.
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = (
                    model_meta.cost_tier if model_meta
                    else (adapter.cost_policy if adapter else CostPolicy.UNKNOWN)
                )
''',
    '''            # Cost is model-specific truth. A provider may expose both free
            # and paid models, so provider-wide FREE_TIER_ALLOWED must never
            # silently bless an unknown model.
            if model_meta is not None:
                cost_tier = model_meta.cost_tier
            elif prov_def is not None:
                cost_tier = CostPolicy.UNKNOWN
            else:
                cost_tier = adapter.cost_policy if adapter else CostPolicy.UNKNOWN
''',
)
replace_exact(
    "integrations/models/gateway.py",
    '''            # 3. Cost Policy Gate
            if prov_def is not None:
                cost_tier = prov_def.cost_policy
            else:
                cost_tier = adapter.cost_policy
''',
    '''            # 3. Model-level Cost Policy Gate
            model_meta = self.model_registry.get_model(cand_provider, cand_model)
            if model_meta is not None:
                cost_tier = model_meta.cost_tier
            elif prov_def is not None:
                cost_tier = CostPolicy.UNKNOWN
            else:
                cost_tier = adapter.cost_policy
''',
)

# ---------------------------------------------------------------------------
# Frontend chat message keeps typed diagnostics without rendering secrets.
# ---------------------------------------------------------------------------
stream_path = ROOT / "frontend/src/chat/streamState.ts"
stream = stream_path.read_text(encoding="utf-8")
old_fields = '''  error_code?: string;
  error_detail?: string;
  attachments?: Array<{
'''
new_fields = '''  error_code?: string;
  error_detail?: string;
  error_category?: string;
  error_retryable?: boolean;
  error_http_status?: number | null;
  error_provider?: string;
  error_model_name?: string;
  error_stage?: string;
  error_agent?: string;
  attachments?: Array<{
'''
if stream.count(old_fields) != 1:
    raise RuntimeError("PATCH_ASSERTION_FAILED streamState error fields")
stream = stream.replace(old_fields, new_fields)
old_sig = '''  errorCode?: string,
  errorDetail?: string
): ChatSessionItem[] {
'''
new_sig = '''  errorCode?: string,
  errorDetail?: string,
  diagnostics?: {
    category?: string; retryable?: boolean; http_status?: number | null;
    provider?: string; model_name?: string; stage?: string; agent?: string;
  }
): ChatSessionItem[] {
'''
if stream.count(old_sig) != 1:
    raise RuntimeError("PATCH_ASSERTION_FAILED streamState error signature")
stream = stream.replace(old_sig, new_sig)
old_assign = '''          error_code: errorCode || 'REQUEST_FAILED',
          error_detail: errorDetail || errorMessage,
'''
new_assign = '''          error_code: errorCode || 'REQUEST_FAILED',
          error_detail: errorDetail || errorMessage,
          error_category: diagnostics?.category,
          error_retryable: diagnostics?.retryable,
          error_http_status: diagnostics?.http_status,
          error_provider: diagnostics?.provider,
          error_model_name: diagnostics?.model_name,
          error_stage: diagnostics?.stage,
          error_agent: diagnostics?.agent,
'''
if stream.count(old_assign) != 1:
    raise RuntimeError("PATCH_ASSERTION_FAILED streamState error assignment")
stream_path.write_text(stream.replace(old_assign, new_assign), encoding="utf-8")

app_path = ROOT / "frontend/src/App.tsx"
app = app_path.read_text(encoding="utf-8")
if app.count(old_fields) != 1:
    raise RuntimeError("PATCH_ASSERTION_FAILED App error fields")
app = app.replace(old_fields, new_fields)
old_call = "applyTerminalErrorToSessions(prev, [turnChatId, assignedChatId], assistantMsgId, errorMsg, safeCode, safeDetail)"
new_call = "applyTerminalErrorToSessions(prev, [turnChatId, assignedChatId], assistantMsgId, errorMsg, safeCode, safeDetail, err)"
if app.count(old_call) != 2:
    raise RuntimeError(f"PATCH_ASSERTION_FAILED App onError calls: {app.count(old_call)}")
app = app.replace(old_call, new_call)
app_path.write_text(app, encoding="utf-8")

print("FULL_DEFECT_SWEEP_V2_PATCH_APPLIED")
