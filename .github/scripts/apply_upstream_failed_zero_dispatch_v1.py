from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")


def remove_range(start_marker: str, end_marker: str, label: str) -> None:
    global text
    if text.count(start_marker) != 1:
        raise SystemExit(f"{label}_START_COUNT={text.count(start_marker)}")
    if text.count(end_marker) != 1:
        raise SystemExit(f"{label}_END_COUNT={text.count(end_marker)}")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    text = text[:start] + text[end:]


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}_COUNT={count}")
    text = text.replace(old, new, 1)


# Remove the existing late guards first. They currently run only after external
# ToolGateway/provider work has already happened.
remove_range(
    '        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":\n',
    '        # Dynamic LLM Intelligence Analysis\n',
    "INTELLIGENCE_LATE_GUARD",
)
remove_range(
    '        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("strategist", {}).get("status") == "FAILED":\n',
    '        # Dynamic LLM Creative Synthesis\n',
    "CREATIVE_LATE_GUARD",
)
remove_range(
    '        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("creative", {}).get("status") == "FAILED":\n',
    '        # RC3 mandatory internal Performance two-pass micro-workflow.\n',
    "PERFORMANCE_LATE_GUARD",
)

# Intelligence: fail before knowledge acquisition, scheduler planning, and the
# three web-search dispatches.
intel_old = '''        emitter = self._get_emitter(context)\n        is_research_mode = bool(emitter and emitter.mode == ProgressMode.RESEARCH_INQUIRY.value)\n        if emitter and not is_research_mode:\n'''
intel_new = '''        emitter = self._get_emitter(context)\n        is_research_mode = bool(emitter and emitter.mode == ProgressMode.RESEARCH_INQUIRY.value)\n        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("cmo_initial", {}).get("status") == "FAILED":\n            context.status = RuntimeStatus.FAILED\n            if emitter:\n                emitter.emit(\n                    ProgressEventType.RUN_FAILED,\n                    stage="INTELLIGENCE",\n                    agent="INTELLIGENCE",\n                    message="Giai đoạn Intelligence thất bại do giai đoạn trước gặp sự cố",\n                    metadata={"error": "PREVIOUS_STAGE_FAILED"},\n                )\n            output = {\n                "stage": "INTELLIGENCE",\n                "agent": "intelligence",\n                "status": "FAILED",\n                "error": "PREVIOUS_STAGE_FAILED",\n                "market_findings": "",\n                "search_receipt_id": None,\n                "citations": [],\n            }\n            context.stage_outputs["intelligence"] = output\n            context.create_checkpoint()\n            return output\n        if emitter and not is_research_mode:\n'''
replace_once(intel_old, intel_new, "INTELLIGENCE_EARLY_GUARD")

# Creative: fail before knowledge acquisition and image-generation dispatch.
creative_old = '''    def execute_stage_creative(self, context: RuntimeContext) -> Dict[str, Any]:\n        """Stage 4: Creative Generation & Asset Synthesis."""\n        context.current_stage = RuntimeStage.CREATIVE\n        emitter = self._get_emitter(context)\n        if emitter:\n'''
creative_new = '''    def execute_stage_creative(self, context: RuntimeContext) -> Dict[str, Any]:\n        """Stage 4: Creative Generation & Asset Synthesis."""\n        context.current_stage = RuntimeStage.CREATIVE\n        emitter = self._get_emitter(context)\n        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("strategist", {}).get("status") == "FAILED":\n            context.status = RuntimeStatus.FAILED\n            if emitter:\n                emitter.emit(\n                    ProgressEventType.RUN_FAILED,\n                    stage="CREATIVE",\n                    agent="CREATIVE",\n                    message="Giai đoạn Creative thất bại do giai đoạn trước gặp sự cố",\n                    metadata={"error": "PREVIOUS_STAGE_FAILED"},\n                )\n            output = {\n                "stage": "CREATIVE",\n                "agent": "creative",\n                "status": "FAILED",\n                "error": "PREVIOUS_STAGE_FAILED",\n                "concept_name": "",\n                "visual_asset_receipt": None,\n                "creative_synthesis": "",\n                "copy_headlines": [],\n                "citations": [],\n            }\n            context.stage_outputs["creative"] = output\n            context.create_checkpoint()\n            return output\n        if emitter:\n'''
replace_once(creative_old, creative_new, "CREATIVE_EARLY_GUARD")

# Performance: fail before knowledge/memory acquisition and analytics retrieval.
performance_old = '''    def execute_stage_performance(self, context: RuntimeContext) -> Dict[str, Any]:\n        """Stage 5: Performance Analytics, Attribution & Experiment Portfolio."""\n        context.current_stage = RuntimeStage.PERFORMANCE\n        emitter = self._get_emitter(context)\n        if emitter:\n'''
performance_new = '''    def execute_stage_performance(self, context: RuntimeContext) -> Dict[str, Any]:\n        """Stage 5: Performance Analytics, Attribution & Experiment Portfolio."""\n        context.current_stage = RuntimeStage.PERFORMANCE\n        emitter = self._get_emitter(context)\n        if context.status == RuntimeStatus.FAILED or context.stage_outputs.get("creative", {}).get("status") == "FAILED":\n            context.status = RuntimeStatus.FAILED\n            if emitter:\n                emitter.emit(\n                    ProgressEventType.RUN_FAILED,\n                    stage="PERFORMANCE",\n                    agent="PERFORMANCE",\n                    message="Giai đoạn Performance thất bại do giai đoạn trước gặp sự cố",\n                    metadata={"error": "PREVIOUS_STAGE_FAILED"},\n                )\n            output = {\n                "stage": "PERFORMANCE",\n                "agent": "performance",\n                "status": "FAILED",\n                "error": "PREVIOUS_STAGE_FAILED",\n                "funnel_kpi": "",\n                "experiment_blueprint": {},\n                "analytics_receipt_id": None,\n                "analytics_data_status": "NOT_ATTEMPTED:PREVIOUS_STAGE_FAILED",\n                "calc_receipt_id": None,\n                "citations": [],\n            }\n            context.stage_outputs["performance"] = output\n            context.create_checkpoint()\n            return output\n        if emitter:\n'''
replace_once(performance_old, performance_new, "PERFORMANCE_EARLY_GUARD")

path.write_text(text, encoding="utf-8")
