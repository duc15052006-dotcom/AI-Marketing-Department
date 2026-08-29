from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all(path: str, old: str, new: str, minimum: int = 1) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"{path}: expected >= {minimum} matches, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new), encoding="utf-8")


def replace_span(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{path}: start marker missing: {start_marker!r}")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{path}: end marker missing: {end_marker!r}")
    p.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


# R1 must have reached the known validated anchor before this continuation.
engine = Path("runtime/engine.py").read_text(encoding="utf-8")
for marker in ("render_agent_skill_context", "self._record_public_error(context, public_err)", "calc_receipt = None"):
    if marker not in engine:
        raise RuntimeError(f"R1_PARTIAL_PATCH_NOT_AT_EXPECTED_ANCHOR: {marker}")

replace_span(
    "runtime/engine.py",
    '            else:\n                logger.exception(f"Unhandled exception during run {context.run_id}: {exc}")',
    '\n\n        if context.status not in (RuntimeStatus.FAILED, RuntimeStatus.CANCELLED)',
    '''            else:
                stage_obj = runtime_stage_to_progress_stage(context.current_stage)
                stage_name = stage_obj.value if hasattr(stage_obj, "value") else str(stage_obj or "")
                stage_to_agent = {
                    "CMO_INITIAL": "CMO", "INTELLIGENCE": "INTELLIGENCE", "STRATEGIST": "STRATEGIST",
                    "CREATIVE": "CREATIVE", "PERFORMANCE": "PERFORMANCE", "FINAL_CMO": "CMO",
                }
                failed_agent = stage_to_agent.get(stage_name, "")
                public_err = internal_runtime_error(stage=stage_name, agent=failed_agent)
                self._record_public_error(context, public_err)
                logger.error("Unhandled runtime exception in run %s (%s)", context.run_id, type(exc).__name__)
                context.status = RuntimeStatus.FAILED
                context.risk_flags.append("RUNTIME_INTERNAL_ERROR")
                final_was_reached = stage_name == "FINAL_CMO"
                cmo_final = {
                    "stage": "FINAL_CMO",
                    "agent": "cmo",
                    "status": "FAILED" if final_was_reached else "NOT_REACHED",
                    "approval_status": "NOT_EVALUATED",
                    "reason": public_err.code,
                    "error": public_err.code,
                    "failed_stage": stage_name or None,
                    "public_error": public_err.model_dump(),
                    "master_gtm_plan": {},
                    "master_gtm_plan_markdown": "# BÁO CÁO THỰC THI THẤT BẠI\\n\\nQuy trình dừng do lỗi runtime nội bộ. Không có bước Final CMO giả lập nào được thực thi.",
                }
                context.stage_outputs["final_cmo"] = cmo_final
                context.create_checkpoint()
                if emitter and not any(e.event_type == ProgressEventType.RUN_FAILED for e in emitter.events):
                    emitter.emit(
                        ProgressEventType.RUN_FAILED,
                        stage=stage_obj,
                        agent=failed_agent or None,
                        message="Quy trình thực thi gặp lỗi runtime nội bộ",
                        metadata={"error": public_err.model_dump()},
                    )
''',
)

# chat/engine.py
replace_once("chat/engine.py", "from typing import Any, Dict, List, Optional\n", "from typing import Any, Callable, Dict, List, Optional\n")
replace_once(
    "chat/engine.py",
    '            "- Never fabricate facts or make up private reasoning.\\n"\n',
    '            "- Never fabricate facts or make up private reasoning.\\n"\n'
    '            "- Never claim you sent email, launched ads, changed budgets, published content, edited an external account, or completed any external action unless an authorized tool execution receipt in this turn proves it. Otherwise describe it as a plan, draft, or capability that still requires execution.\\n"\n',
)
replace_once(
    "chat/engine.py",
    '''        history_msgs = [m for m in session.messages if m.content != user_message]
        recent_history = history_msgs[-8:]
''',
    '''        history_msgs = list(session.messages)
        if history_msgs:
            last = history_msgs[-1]
            last_role = last.role.value if hasattr(last.role, "value") else str(last.role)
            if last_role == ChatRole.USER.value and last.content == user_message:
                history_msgs = history_msgs[:-1]
        recent_history = history_msgs[-12:]
''',
)
replace_once("chat/engine.py", "from runtime.progress import (\n", "from runtime.public_errors import from_model_response, from_stream_delta, internal_runtime_error\nfrom runtime.progress import (\n")
replace_span(
    "chat/engine.py",
    "            had_error = False\n            error_detail = \"\"\n",
    "\n        # Fallback to synchronous generate when no text delta sink is provided",
    '''            public_error = None
            try:
                stream_gen = self.model_gateway.generate_stream(req)
                for delta in stream_gen:
                    if delta.provider:
                        last_provider = delta.provider
                    if delta.model_name:
                        last_model_name = delta.model_name
                    if delta.content:
                        chunks.append(delta.content)
                        text_delta_sink(delta.content)
                    if delta.finish_reason == "error":
                        public_error = from_stream_delta(delta, stage="GENERAL_CONVERSATION", agent="")
                        break
            except (GeneratorExit, KeyboardInterrupt, SystemExit):
                raise
            except Exception as ex:
                logger.error("General chat stream failed at runtime boundary (%s)", type(ex).__name__)
                public_error = internal_runtime_error(stage="GENERAL_CONVERSATION", agent="")

            if chunks and public_error is None:
                content = "".join(chunks).strip()
                if emitter:
                    emitter.emit(ProgressEventType.RUN_COMPLETED, message="Hoàn tất phản hồi hội thoại")
                return {
                    "success": True,
                    "content": content,
                    "model_used": last_model_name or req.model_name,
                    "provider": last_provider,
                    "mode": "DOCUMENT_ANALYSIS" if is_document_analysis else "GENERAL_CONVERSATION",
                }

            if public_error is None:
                public_error = internal_runtime_error(stage="GENERAL_CONVERSATION", agent="")
            if emitter:
                emitter.emit(
                    ProgressEventType.RUN_FAILED,
                    message=public_error.safe_message,
                    metadata={"error": public_error.model_dump()},
                )
            return {
                "success": False,
                "error": public_error.code,
                "public_error": public_error.model_dump(),
                "content": f"⚠️ Không thể hoàn tất phản hồi: {public_error.safe_message}\\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
            }
''',
)
replace_span(
    "chat/engine.py",
    '        error_detail = resp.error or "Model provider is currently unavailable or quota limit reached."',
    '\n    def _render_history',
    '''        public_error = from_model_response(resp, stage="GENERAL_CONVERSATION", agent="")
        logger.warning("UniversalModelGateway chat generation failed with %s", public_error.code)
        if emitter:
            emitter.emit(
                ProgressEventType.RUN_FAILED,
                message=public_error.safe_message,
                metadata={"error": public_error.model_dump()},
            )
        return {
            "success": False,
            "error": public_error.code,
            "public_error": public_error.model_dump(),
            "content": f"⚠️ Không thể hoàn tất phản hồi: {public_error.safe_message}\\nTin nhắn của bạn đã được lưu trong lịch sử phiên.",
        }
''',
)

# app_api/server.py
replace_once("app_api/server.py", "from chat.engine import ChatConversationEngine\n", "from chat.engine import ChatConversationEngine\nfrom chat.conversation_state import FollowupIntent, resolve_conversation_turn\n")
replace_once("app_api/server.py", "from runtime.context_compiler import ContextCompiler\n", "from runtime.context_compiler import ContextCompiler\nfrom runtime.public_errors import internal_runtime_error\n")
stream_route = '''                decision = APP_BACKEND.conversation_router.route(
                    message=user_text,
                    attachments=parsed_attachments,
                    chat_history=session.messages,
                    project_id=session.optional_project_id,
                    business_id=session.optional_business_id,
                )
'''
stream_route_new = '''                resolved_turn = resolve_conversation_turn(session.messages, user_text)
                route_text = resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text
                decision = APP_BACKEND.conversation_router.route(
                    message=route_text,
                    attachments=parsed_attachments,
                    chat_history=session.messages,
                    project_id=session.optional_project_id,
                    business_id=session.optional_business_id,
                )
                if resolved_turn.followup_intent == FollowupIntent.TRANSFORM_EXISTING:
                    from chat.router import RoutingDecision
                    decision = RoutingDecision(ConversationIntent.GENERAL_CONVERSATION, 1.0, resolved_turn.reason_code)
                elif resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH:
                    from chat.router import RoutingDecision
                    decision = RoutingDecision(ConversationIntent.RESEARCH_INQUIRY, 1.0, resolved_turn.reason_code, {"research_depth": "DEEP"})
'''
replace_once("app_api/server.py", stream_route, stream_route_new)
replace_once(
    "app_api/server.py",
    '''            decision = APP_BACKEND.conversation_router.route(
                message=user_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
''',
    '''            resolved_turn = resolve_conversation_turn(session.messages, user_text)
            route_text = resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text
            decision = APP_BACKEND.conversation_router.route(
                message=route_text,
                attachments=parsed_attachments,
                chat_history=session.messages,
                project_id=session.optional_project_id,
                business_id=session.optional_business_id,
            )
            if resolved_turn.followup_intent == FollowupIntent.TRANSFORM_EXISTING:
                from chat.router import RoutingDecision
                decision = RoutingDecision(ConversationIntent.GENERAL_CONVERSATION, 1.0, resolved_turn.reason_code)
            elif resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH:
                from chat.router import RoutingDecision
                decision = RoutingDecision(ConversationIntent.RESEARCH_INQUIRY, 1.0, resolved_turn.reason_code, {"research_depth": "DEEP"})
''',
)
replace_all("app_api/server.py", "objective=user_text,", "objective=(resolved_turn.effective_text if resolved_turn.followup_intent == FollowupIntent.DEEPEN_RESEARCH else user_text),", minimum=2)
replace_all("app_api/server.py", 'bridge.send_error(res.get("error") or "Execution failed")', 'bridge.send_error(res.get("public_error") or internal_runtime_error(stage=decision.intent.value).model_dump())', minimum=2)
replace_once("app_api/server.py", 'bridge.send_error(intel_out.get("error") or "RESEARCH_FAILED")', 'bridge.send_error(APP_BACKEND.runtime.get_public_error(ctx.run_id) or internal_runtime_error(stage="INTELLIGENCE", agent="INTELLIGENCE").model_dump())')
replace_span(
    "app_api/server.py",
    '                        root_err = cmo_final.get("error") or cmo_final.get("reason") or "WORKFLOW_FAILED"',
    '\n\n            except Exception as ex:',
    '''                        bridge.send_error(
                            cmo_final.get("public_error")
                            or APP_BACKEND.runtime.get_public_error(ctx.run_id)
                            or internal_runtime_error(stage=cmo_final.get("failed_stage") or "").model_dump()
                        )
''',
)
replace_once(
    "app_api/server.py",
    '''            except Exception as ex:
                logger.exception(f"Streaming execution error for chat {chat_id}: {ex}")
                bridge.send_error(ex)
''',
    '''            except Exception as ex:
                logger.error("Streaming execution failed for chat %s (%s)", chat_id, type(ex).__name__)
                bridge.send_error(internal_runtime_error(stage="STREAMING_API").model_dump())
''',
)

# tools/adapters.py fake-success defaults become explicit unavailable MOCKs.
replace_span("tools/adapters.py", "        # Mock / Provider-neutral search results\n", "\n\n\nclass HttpAdapter", '''        return AdapterResult(
            success=False,
            error_code="SEARCH_PROVIDER_NOT_CONFIGURED",
            error_message="No real search provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        return AdapterResult(\n            success=True,\n            data={\n                \"url\": url,", "\n\n\nclass CreativeTextAdapter", '''        return AdapterResult(
            success=False,
            error_code="HTTP_PROVIDER_NOT_CONFIGURED",
            error_message="No real webpage reader is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        return AdapterResult(\n            success=True,\n            data={\"generated_copy\":", "\n\n\nclass MediaCreationAdapter", '''        return AdapterResult(
            success=False,
            error_code="TEXT_TOOL_NOT_CONFIGURED",
            error_message="No executable text-generation tool is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        asset_type = \"video\" if \"video\" in capability_id else \"image\"", "\n\n\nclass PublishingAdapter", '''        asset_type = "video" if "video" in capability_id else "image"
        return AdapterResult(
            success=False,
            data={"asset_type": asset_type, "status": "NOT_EXECUTED"},
            error_code="MEDIA_PROVIDER_NOT_CONFIGURED",
            error_message="No real media renderer is bound. A creative specification may be produced, but no asset was rendered.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        platform = parameters.get(\"platform\", \"generic\")", "\n\n\nclass AnalyticsAdapter", '''        return AdapterResult(
            success=False,
            error_code="PUBLISH_PROVIDER_NOT_CONFIGURED",
            error_message="No publishing connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        metric_name = parameters.get(\"metric_name\", \"roas\")", "\n\n\nclass FileStorageAdapter", '''        return AdapterResult(
            success=False,
            error_code="ANALYTICS_PROVIDER_NOT_CONFIGURED",
            error_message="No real analytics dataset/provider is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_span("tools/adapters.py", "        action = \"read\" if \"read\" in capability_id else \"write\"", "\n\n\nclass ObservationSearchAdapter", '''        return AdapterResult(
            success=False,
            error_code="FILE_PROVIDER_NOT_CONFIGURED",
            error_message="No real file connector is bound to this adapter.",
            latency_ms=(time.perf_counter() - start) * 1000.0,
            execution_mode=ExecutionMode.MOCK,
        )
''')
replace_once("tools/adapters.py", '                "language": parameters.get("language", "en"),\n', '                "language": parameters.get("language") or ("vi" if any(ch in query.lower() for ch in "ăâđêôơưáàảãạéèẻẽẹíìỉĩịóòỏõọúùủũụýỳỷỹỵ") else "en"),\n')
replace_once("tools/adapters.py", '                error_message=str(exc),\n', '                error_message=f"Observation gateway failed ({type(exc).__name__}).",\n')

replace_once("tools/tool_gateway.py", '            err_msg = adapter_res.error_message if adapter_res else str(last_exc)\n', '            err_msg = adapter_res.error_message if adapter_res else (f"Adapter execution failed ({type(last_exc).__name__})." if last_exc else "Adapter execution failed.")\n')

replace_once("connectors/analytics_connector.py", "                execution_mode=ExecutionMode.MOCK,\n            )\n\n        elif cap in (\"attribution_data_access\", \"experiment_result_analysis\"):\n            return AdapterResult(\n                success=True,", "                execution_mode=ExecutionMode.REAL,\n            )\n\n        elif cap in (\"attribution_data_access\", \"experiment_result_analysis\"):\n            return AdapterResult(\n                success=False,")
replace_span("connectors/analytics_connector.py", '                success=False,\n                data={\n                    "attribution_model": "DATA_DRIVEN_MULTI_TOUCH",', "\n\n        return AdapterResult(\n            success=False,", '''                success=False,
                error_code="MISSING_OBSERVED_DATA",
                error_message="Attribution or experiment conclusions require explicit observed campaign/experiment data.",
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                execution_mode=ExecutionMode.MOCK,
            )
''')

replace_once("frontend/src/App.tsx", "        const safeDetail = err.message || 'Không thể nhận phản hồi từ backend.';\n", "        const safeDetail = err.safe_message || err.message || 'Không thể nhận phản hồi từ backend.';\n")
replace_once("frontend/src/App.tsx", "        setWorkflowStages((prev) => applyTerminalErrorToStages(prev));\n        setAgentStates((prev) => applyTerminalErrorToAgents(prev));\n", "        setWorkflowStages((prev) => applyTerminalErrorToStages(prev, err));\n        setAgentStates((prev) => applyTerminalErrorToAgents(prev, err));\n")

print("full hardening continuation patch applied")
