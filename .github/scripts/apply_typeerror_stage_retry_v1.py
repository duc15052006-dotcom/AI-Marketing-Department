from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}_COUNT={count}")
    text = text.replace(old, new, 1)


replace_once(
    "import hashlib\nimport json\n",
    "import hashlib\nimport inspect\nimport json\n",
    "IMPORT_INSPECT",
)

helper_anchor = '''    def _execute_tool_singleflight(self, idem_key: str, request: ToolRequest) -> ExecutionReceipt:\n'''
helper = '''    @staticmethod\n    def _stage_supports_text_delta_sink(stage_callable: Any) -> bool:\n        """Return whether a stage callable can accept ``text_delta_sink``.\n\n        Compatibility is resolved *before* stage execution. We never probe by\n        calling a stage and catching TypeError because the stage may already\n        have performed provider/tool side effects before raising it.\n        """\n        try:\n            params = inspect.signature(stage_callable).parameters\n        except (TypeError, ValueError):\n            # Opaque callables fail closed to the legacy one-argument form.\n            return False\n\n        explicit = params.get("text_delta_sink")\n        if explicit is not None and explicit.kind in (\n            inspect.Parameter.POSITIONAL_OR_KEYWORD,\n            inspect.Parameter.KEYWORD_ONLY,\n        ):\n            return True\n        return any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())\n\n''' + helper_anchor
replace_once(helper_anchor, helper, "STAGE_SIGNATURE_HELPER")

final_old = '''            # Stage 6: Final CMO (Governed Synthesis & Master GTM Plan)\n            if context.status != RuntimeStatus.FAILED:\n                if text_delta_sink is not None:\n                    try:\n                        cmo_final = self.execute_stage_final_cmo(context, text_delta_sink=text_delta_sink)\n                    except TypeError:\n                        cmo_final = self.execute_stage_final_cmo(context)\n                else:\n                    try:\n                        cmo_final = self.execute_stage_final_cmo(context)\n                    except TypeError:\n                        cmo_final = self.execute_stage_final_cmo(context, text_delta_sink=None)\n            else:\n'''
final_new = '''            # Stage 6: Final CMO (Governed Synthesis & Master GTM Plan)\n            if context.status != RuntimeStatus.FAILED:\n                final_stage = self.execute_stage_final_cmo\n                if text_delta_sink is not None and self._stage_supports_text_delta_sink(final_stage):\n                    cmo_final = final_stage(context, text_delta_sink=text_delta_sink)\n                else:\n                    cmo_final = final_stage(context)\n            else:\n'''
replace_once(final_old, final_new, "FINAL_CMO_SINGLE_INVOCATION")

research_old = '''            # Execute Intelligence stage only — search, evidence, grounding, synthesis\n            if text_delta_sink is not None:\n                try:\n                    intel_out = self.execute_stage_intelligence(context, text_delta_sink=text_delta_sink)\n                except TypeError:\n                    intel_out = self.execute_stage_intelligence(context)\n            else:\n                try:\n                    intel_out = self.execute_stage_intelligence(context)\n                except TypeError:\n                    intel_out = self.execute_stage_intelligence(context, text_delta_sink=None)\n\n            # Set terminal status based on Intelligence outcome\n'''
research_new = '''            # Execute Intelligence stage only — search, evidence, grounding, synthesis.\n            # Signature compatibility is resolved before execution so an internal\n            # TypeError can never trigger a duplicate stage/provider invocation.\n            intelligence_stage = self.execute_stage_intelligence\n            if text_delta_sink is not None and self._stage_supports_text_delta_sink(intelligence_stage):\n                intel_out = intelligence_stage(context, text_delta_sink=text_delta_sink)\n            else:\n                intel_out = intelligence_stage(context)\n\n            # Set terminal status based on Intelligence outcome\n'''
replace_once(research_old, research_new, "RESEARCH_SINGLE_INVOCATION")

path.write_text(text, encoding="utf-8")
