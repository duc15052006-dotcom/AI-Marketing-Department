"""Targeted Certification Tests for PROD-UAT-WORKFLOW-FAILURE-SEMANTICS-01.

Validates:
1. Workflow Failure Gate: Early stage failure prevents execution of unreached stages and Final CMO.
2. Final CMO Progress Truth: Zero STAGE_STARTED events for unreached Final CMO.
3. First Root Error Preservation: Original failing stage and error code/message are preserved without PREVIOUS_STAGE_FAILED obscuration.
4. Streaming Handoff Firewall: HandoffStreamFilter prevents === STRUCTURED HANDOFF === and JSON from reaching delta sinks across arbitrary chunk boundaries.
5. Incremental Streaming: Normal text streams incrementally with zero latency.
6. Handoff Extraction Preservation: extract_handoff_payload retains 100% fidelity on raw text.
"""

import json
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from runtime.context import RuntimeContext, RuntimeStage, RuntimeStatus
from runtime.engine import FiveAgentDepartmentRuntime
from runtime.handoff import (
    HANDOFF_SENTINEL,
    HandoffStreamFilter,
    extract_handoff_payload,
    strip_handoff_block,
)
from runtime.progress import ProgressEventType, ProgressMode, ProgressSink


class TestWorkflowFailureSemantics01(unittest.TestCase):
    """Targeted tests for workflow failure gate and root error preservation."""

    def setUp(self) -> None:
        self.engine = FiveAgentDepartmentRuntime()

    def test_01_cmo_initial_failure_guards_final_cmo_and_preserves_root_error(self) -> None:
        """Assert CMO_INITIAL failure halts workflow, executes 0 downstream stages, and retains root error."""
        progress_events = []

        def sink(evt: Dict[str, Any]) -> None:
            progress_events.append(evt)

        # Mock _call_agent_llm to fail on CMO_INITIAL with a deterministic root error
        def mock_call_agent_llm(agent_id, sys_prompt, user_prompt, context=None, text_delta_sink=None):
            if agent_id == "cmo":
                return None, "TEST_CMO_PROVIDER_TIMEOUT"
            return "Unexpected agent call", None

        with patch.object(self.engine, "_call_agent_llm", side_effect=mock_call_agent_llm):
            ctx, cmo_final, artifact = self.engine.run_workflow(
                objective="Test campaign objective",
                business_id="BIZ_TEST",
                chat_id="CHAT_TEST",
                progress_sink=sink,
            )

        # 1. Context and Artifact terminal status
        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(artifact.status, RuntimeStatus.FAILED)

        # 2. CMO_INITIAL status in stage outputs
        cmo_init = ctx.stage_outputs.get("cmo_initial", {})
        self.assertEqual(cmo_init.get("status"), "FAILED")
        self.assertEqual(cmo_init.get("error"), "TEST_CMO_PROVIDER_TIMEOUT")

        # 3. Downstream stages must NOT have executed
        self.assertNotIn("intelligence", ctx.stage_outputs)
        self.assertNotIn("strategist", ctx.stage_outputs)
        self.assertNotIn("creative", ctx.stage_outputs)
        self.assertNotIn("performance", ctx.stage_outputs)

        # 4. Final CMO output must reflect NOT_REACHED and retain original root error
        self.assertEqual(cmo_final.get("status"), "NOT_REACHED")
        self.assertEqual(cmo_final.get("failed_stage"), "CMO_INITIAL")
        self.assertEqual(cmo_final.get("error"), "TEST_CMO_PROVIDER_TIMEOUT")
        self.assertEqual(cmo_final.get("reason"), "TEST_CMO_PROVIDER_TIMEOUT")
        self.assertNotIn("PREVIOUS_STAGE_FAILED", str(cmo_final.get("error")))
        self.assertNotIn("PREVIOUS_STAGE_FAILED", str(cmo_final.get("reason")))

        # 5. Progress Events: Zero FINAL_CMO STAGE_STARTED events!
        final_cmo_started = [e for e in progress_events if getattr(e, "stage", None) == "FINAL_CMO" and getattr(e, "event_type", None) == "STAGE_STARTED"]
        self.assertEqual(len(final_cmo_started), 0, "FINAL_CMO STAGE_STARTED must be 0 on early failure")

        # CMO_INITIAL must have STAGE_STARTED and RUN_FAILED
        cmo_started = [e for e in progress_events if e.get("stage") == "CMO_INITIAL" and e.get("event_type") == "STAGE_STARTED"]
        cmo_failed = [e for e in progress_events if e.get("stage") == "CMO_INITIAL" and e.get("event_type") == "RUN_FAILED"]
        self.assertEqual(len(cmo_started), 1)
        self.assertEqual(len(cmo_failed), 1)

    def test_02_mid_workflow_failure_preserves_failing_stage_and_guards_final_cmo(self) -> None:
        """Assert failure in Stage 3 (Strategist) skips Stages 4, 5, 6 and preserves Strategist root error."""
        progress_events = []

        def sink(evt: Dict[str, Any]) -> None:
            progress_events.append(evt)

        def mock_call_agent_llm(agent_id, sys_prompt, user_prompt, context=None, text_delta_sink=None):
            if agent_id == "cmo":
                return "CMO Initial strategic directive", None
            elif agent_id == "intelligence":
                return "Market findings and consumer trends", None
            elif agent_id == "strategist":
                return None, "STRATEGIST_GATEWAY_RATE_LIMIT"
            return "Unexpected agent call", None

        with patch.object(self.engine, "_call_agent_llm", side_effect=mock_call_agent_llm):
            ctx, cmo_final, artifact = self.engine.run_workflow(
                objective="Test campaign objective",
                business_id="BIZ_TEST",
                chat_id="CHAT_TEST",
                progress_sink=sink,
            )

        self.assertEqual(ctx.status, RuntimeStatus.FAILED)
        self.assertEqual(ctx.stage_outputs.get("cmo_initial", {}).get("status"), "COMPLETED")
        self.assertEqual(ctx.stage_outputs.get("intelligence", {}).get("status"), "COMPLETED")
        self.assertEqual(ctx.stage_outputs.get("strategist", {}).get("status"), "FAILED")
        self.assertNotIn("creative", ctx.stage_outputs)
        self.assertNotIn("performance", ctx.stage_outputs)

        self.assertEqual(cmo_final.get("status"), "NOT_REACHED")
        self.assertEqual(cmo_final.get("failed_stage"), "STRATEGIST")
        self.assertEqual(cmo_final.get("error"), "STRATEGIST_GATEWAY_RATE_LIMIT")
        self.assertNotIn("PREVIOUS_STAGE_FAILED", str(cmo_final.get("error")))

        final_cmo_started = [e for e in progress_events if getattr(e, "stage", None) == "FINAL_CMO" and getattr(e, "event_type", None) == "STAGE_STARTED"]
        self.assertEqual(len(final_cmo_started), 0)


class TestStreamingHandoffFirewall(unittest.TestCase):
    """Targeted tests for HandoffStreamFilter and strip_handoff_block."""

    def test_01_normal_streaming_with_handoff_blocks_delimiter_and_json(self) -> None:
        """Assert stream sink receives visible prose only, dropping === STRUCTURED HANDOFF ===."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        full_output = (
            "Here is the complete market strategy.\n"
            "1. Focus on Gen Z audience.\n"
            "2. Optimize for video channels.\n\n"
            f"{HANDOFF_SENTINEL}\n"
            '```json\n'
            '{"facts": [{"text": "Gen Z prefers short-form video"}]}\n'
            '```'
        )

        filter_sink.on_delta(full_output)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertIn("Here is the complete market strategy.", result)
        self.assertNotIn(HANDOFF_SENTINEL, result)
        self.assertNotIn('"facts"', result)
        self.assertNotIn("```json", result)

    def test_02_fragmented_delimiter_two_chunks(self) -> None:
        """Assert delimiter split across 2 chunks is detected without partial leak."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        chunk1 = "Strategic synthesis conclusion.\n\n=== STRUCT"
        chunk2 = "URED HANDOFF ===\n```json\n{\"facts\": []}\n```"

        filter_sink.on_delta(chunk1)
        filter_sink.on_delta(chunk2)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertEqual(result, "Strategic synthesis conclusion.\n\n")
        self.assertNotIn("===", result)
        self.assertNotIn("STRUCT", result)

    def test_03_fragmented_delimiter_three_chunks(self) -> None:
        """Assert delimiter split across 3 chunks is detected cleanly."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        chunk1 = "Important analysis text.\n==="
        chunk2 = " STRUCTURED "
        chunk3 = "HANDOFF ===\n```json\n{}"

        filter_sink.on_delta(chunk1)
        filter_sink.on_delta(chunk2)
        filter_sink.on_delta(chunk3)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertEqual(result, "Important analysis text.\n")
        self.assertNotIn("===", result)

    def test_04_fragmented_delimiter_single_char_stream(self) -> None:
        """Assert delimiter split character-by-character is detected cleanly."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        stream = "Analysis.\n" + HANDOFF_SENTINEL + "\n```json\n{}"
        for char in stream:
            filter_sink.on_delta(char)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertEqual(result, "Analysis.\n")

    def test_05_no_handoff_stream_passes_all_text_incrementally(self) -> None:
        """Assert normal stream with no handoff passes all text without omission or duplication."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        chunks = ["Hello ", "world, ", "this ", "is ", "a ", "normal ", "response."]
        for c in chunks:
            filter_sink.on_delta(c)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertEqual(result, "Hello world, this is a normal response.")

    def test_06_handoff_like_words_not_truncated(self) -> None:
        """Assert ordinary prose containing 'structured' or 'handoff' is not truncated."""
        deltas = []
        filter_sink = HandoffStreamFilter(sink=lambda d: deltas.append(d))

        chunks = [
            "We recommend a structured approach to marketing.\n",
            "The handoff between teams should be smooth.\n",
            "=== Section Header ===\n",
            "More content here.",
        ]
        for c in chunks:
            filter_sink.on_delta(c)
        filter_sink.flush()

        result = "".join(deltas)
        self.assertEqual(result, "".join(chunks))

    def test_07_strip_handoff_block_and_extract_payload(self) -> None:
        """Assert strip_handoff_block removes delimiter and extract_handoff_payload parses JSON."""
        raw_text = (
            "Market research findings for decor products.\n"
            "Key demand is in minimalist styles.\n\n"
            f"{HANDOFF_SENTINEL}\n"
            "```json\n"
            "{\n"
            '  "facts": [{"text": "Minimalist decor leads search volume", "evidence_refs": ["EVID-1"]}],\n'
            '  "observations": ["TikTok drives impulse buys"]\n'
            "}\n"
            "```"
        )

        clean_prose = strip_handoff_block(raw_text)
        self.assertEqual(
            clean_prose,
            "Market research findings for decor products.\nKey demand is in minimalist styles.",
        )
        self.assertNotIn(HANDOFF_SENTINEL, clean_prose)

        parse_status, payload = extract_handoff_payload(raw_text)
        self.assertEqual(parse_status, "OK")
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload.get("facts", [])), 1)
        self.assertEqual(payload["facts"][0]["text"], "Minimalist decor leads search volume")
        self.assertEqual(len(payload.get("observations", [])), 1)


if __name__ == "__main__":
    unittest.main()
