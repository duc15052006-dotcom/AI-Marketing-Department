# Tool and chat integration candidate v1

This draft combines three independently scoped fixes to check their interaction.
It is not approval to merge main or certification of the entire application.

## Pinned inputs

Baseline main: `3fed5e1e3b07fa45cd657cd4e4350740dac6b181`.

| Original PR | Exact head | Included production change |
| --- | --- | --- |
| #164 | `461c1c0ac31b473e24ea2f6991e57d7205e73c0d` | Cap effective timeout at capability policy; preserve smaller caller limits. |
| #168 | `76bcb4f72d4d61482078a28f4d4dc59e2a8b718c` | Return an error receipt before dispatch for UNAVAILABLE capabilities. |
| #160 | `9754d473b6258adb40cdf4a246bd84b70ad1680d` | Persist attachment ownership per message and migrate chat schema V1 to V2. |

All three inputs have the same baseline. No dependency on the other open PRs
was found for these changes. Both ToolGateway changes must be retained: copying
either original branch's whole file would discard the other fix.

The original regression tests and three dedicated workflows are copied unchanged.
Production changes are restricted to `tools/tool_gateway.py` and `chat/repository.py`.
The offline workflow additionally checks out the literal candidate SHA, asserts
the checkout identity, and runs the combined regressions before the existing full suite.

## Reproduction and evidence

Tests-only RED commit: `38043d5d325f55b5ca65b0bf05ebb5cdf3928383`.
Its tree `686cdceedd9130e2f0f545b678a519662a92f330` matches the local staged tree used
for the baseline check. Production at that checkpoint is unchanged main.

```bash
python -m unittest -v \
  tests.test_tool_gateway_timeout_policy_ceiling_adversarial_v1 \
  tests.test_tool_gateway_capability_availability_gate_adversarial_v1 \
  tests.test_chat_attachment_message_link_adversarial_v1
```

Baseline result: 6 tests, 4 assertion failures, 0 errors, 2 passing controls.
Failures demonstrate timeout 600 instead of 15, dispatch despite UNAVAILABLE,
cross-message attachment hydration, and assignment of a session-only file to a message.

Local candidate check:

```bash
python -m unittest -v \
  tests.test_tool_gateway_timeout_policy_ceiling_adversarial_v1 \
  tests.test_tool_gateway_capability_availability_gate_adversarial_v1 \
  tests.test_chat_attachment_message_link_adversarial_v1 \
  tests.test_chat_persistence_v1 \
  tests.test_tool_gateway_idempotency_01 \
  tests.test_free_only_cost_authority_02 \
  tests.test_tool_receipt_provenance_04
```

Result: 43 tests, OK, no skips. An additional local experiment created a real V1
database with the baseline repository, then opened it with the candidate: the
legacy attachment remained in the session inventory, its unknown message owner
stayed NULL, schema advanced to V2, reopening succeeded, and foreign_key_check
reported no violations. This experiment is separate from the 43 unittest cases.

Hosted full-suite results belong in the PR body with the exact final head SHA,
run URL, observed test counts, and identity log. Do not infer a pass from this document.
The hosted run has all three live-provider/model test flags set to zero.

## Review and rollback limits

- Preserve the original PRs; this branch is a bounded integration candidate.
- V1 did not store attachment-to-message ownership. Migration cannot reconstruct
  missing historical ownership. Old files remain accessible in the session inventory.
- Restore a database snapshot taken before migration if a schema rollback is
  required; reverting Python code does not undo schema V2 or restore absent V1 metadata.
- No changes to provider credentials, production data, branch protection, or main.
- Knowledge/memory durability, retrieval/citation issues, brain runtime wiring,
  queue limits, and the other open PRs remain outside this candidate.
- This is a single-agent implementation and verification pass, not independent review.

## Handoff for GPT 5.6

1. Read live main and this PR's exact head before acting. Compare against the pinned inputs.
2. Inspect both ToolGateway changes together and the attachment migration semantics.
3. Read actual CI job logs; confirm expected_sha equals actual_sha and PR head,
   then check candidate and full-suite summaries and uploaded evidence metadata.
4. If another defect is reproduced, isolate it in a separate small branch and regression.
5. Keep this PR draft until review; do not merge main without the owner's explicit command.
