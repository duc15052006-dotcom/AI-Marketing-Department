"""Regression coverage for fail-closed handling of truncated model JSON."""

import unittest

from integrations.models.invocation import OutputValidationState, parse_and_validate_agent_json


class NoSyntheticJsonRepair24Tests(unittest.TestCase):
    def test_direct_complete_json_is_valid(self):
        state, data = parse_and_validate_agent_json('{"output":{"summary":"ok"},"confidence":"HIGH"}')
        self.assertEqual(state, OutputValidationState.VALID)
        self.assertEqual(data["output"]["summary"], "ok")

    def test_complete_fenced_json_can_be_unwrapped(self):
        state, data = parse_and_validate_agent_json(
            '```json\n{"output":{"summary":"ok"},"confidence":"HIGH"}\n```'
        )
        self.assertEqual(state, OutputValidationState.REPAIRABLE)
        self.assertEqual(data["confidence"], "HIGH")

    def test_complete_json_surrounded_by_prose_can_be_unwrapped(self):
        state, data = parse_and_validate_agent_json(
            'Result follows: {"output":{"summary":"ok"},"confidence":"MEDIUM"} end.'
        )
        self.assertEqual(state, OutputValidationState.REPAIRABLE)
        self.assertEqual(data["confidence"], "MEDIUM")

    def test_truncated_object_is_invalid_instead_of_suffix_repaired(self):
        state, data = parse_and_validate_agent_json(
            '{"output":{"summary":"cut off"},"confidence":"HIGH"'
        )
        self.assertEqual(state, OutputValidationState.INVALID)
        self.assertIsNone(data)

    def test_truncated_nested_array_is_invalid(self):
        state, data = parse_and_validate_agent_json(
            '{"output":{"items":[1,2,3],"summary":"cut"'
        )
        self.assertEqual(state, OutputValidationState.INVALID)
        self.assertIsNone(data)

    def test_trailing_comma_truncation_is_invalid(self):
        state, data = parse_and_validate_agent_json('{"output":{"summary":"cut"},')
        self.assertEqual(state, OutputValidationState.INVALID)
        self.assertIsNone(data)

    def test_missing_quote_cannot_be_invented(self):
        state, data = parse_and_validate_agent_json('{"output":{"summary":"cut off')
        self.assertEqual(state, OutputValidationState.INVALID)
        self.assertIsNone(data)


if __name__ == "__main__":
    unittest.main()
