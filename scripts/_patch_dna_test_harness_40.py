from pathlib import Path


def replace_stage_detector(path_str: str, resolved_agent_expr: str) -> None:
    path = Path(path_str)
    text = path.read_text(encoding="utf-8")
    start_anchor = '        sys_msg = request.messages[0].content if request.messages else ""\n'
    end_anchor = '        if self.fail_stage and self.fail_stage == stage:\n'
    if text.count(start_anchor) != 1 or text.count(end_anchor) != 1:
        raise SystemExit(
            f"{path_str}: detector anchors start={text.count(start_anchor)} end={text.count(end_anchor)}"
        )
    start = text.index(start_anchor)
    end = text.index(end_anchor, start)
    replacement = (
        start_anchor
        + '        stage_directive = sys_msg.split("=== CURRENT RUNTIME STAGE DIRECTIVE ===", 1)[-1]\n'
        + f'        resolved_agent = {resolved_agent_expr}\n'
        + '        if resolved_agent == "cmo":\n'
        + '            stage = (\n'
        + '                "final_cmo"\n'
        + '                if any(marker in stage_directive for marker in (\n'
        + '                    "Final Governed Go-To-Market",\n'
        + '                    "Final Governed Strategy",\n'
        + '                    "governed final synthesis",\n'
        + '                ))\n'
        + '                else "cmo_initial"\n'
        + '            )\n'
        + '        elif resolved_agent in {"intelligence", "strategist", "creative", "performance"}:\n'
        + '            stage = resolved_agent\n'
        + '        else:\n'
        + '            stage = "unknown"\n\n'
    )
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


replace_stage_detector(
    "tests/test_prod_core_authority_01a.py",
    'agent_id or (request.metadata or {}).get("agent_id")',
)
replace_stage_detector(
    "tests/test_prod_runtime_01_single_run_authority.py",
    'kwargs.get("agent_id") or (request.metadata or {}).get("agent_id")',
)

wiring_path = Path("tests/test_runtime_agent_dna_wiring_28.py")
wiring = wiring_path.read_text(encoding="utf-8")
old_marker = '            "strategist": "Marketing Strategist",\n'
new_marker = '            "strategist": "Marketing Strategy & Growth Architect",\n'
if wiring.count(old_marker) != 1:
    raise SystemExit(f"DNA_MARKER_COUNT={wiring.count(old_marker)}")
wiring_path.write_text(wiring.replace(old_marker, new_marker, 1), encoding="utf-8")
