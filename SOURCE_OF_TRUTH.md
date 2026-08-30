# AI Marketing Department — Source of Truth

This file defines how humans and AI coding agents must resolve conflicting repository documentation.

## Authority order

Use the following order from highest to lowest authority:

1. **Code and automated tests at the checked-out commit** — executable behavior and enforced invariants are authoritative for what the system currently does.
2. **`STATUS_MATRIX.md`** — authoritative chronological record of implemented/tested/runtime-verified project phases and known incomplete gates.
3. **`ARCHITECTURE.md` and `AGENT_PROTOCOL.md`** — authoritative current architecture and agent/collaboration contracts where they do not conflict with newer executable behavior or status evidence.
4. **Phase-specific evaluation/certification artifacts** — valid only for the exact commit, benchmark, dataset, and environment they identify.
5. **Historical gap, planning, or certification documents** — forensic history only. They must never override newer code, tests, or status records.

When two sources conflict, prefer the higher-authority source. Within the same tier, prefer the source tied to the newer verified commit/evidence. Never silently average contradictory claims.

## Permanent system invariants

- The department has exactly **5 permanent logical agents**: `CMO`, `Intelligence`, `Strategist`, `Creative`, and `Performance`.
- There is no Agent 6. The CMO may appear at multiple workflow stages but remains one logical agent.
- Preserve the existing supervised Five-Agent runtime and Human Approval Gate for consequential publishing, external-write, financial, or high-risk actions.
- Do not introduce autonomous self-modification or unsupervised public publishing as a shortcut.
- Provider/model choice is configuration-driven through the Universal Model Gateway / Provider Registry. Agent logic must not hard-code a provider dependency.
- Provider cost governance must fail closed. Paid/unknown providers may not be silently treated as free.
- Security, provenance, approval, and receipt evidence must be truthful even on failure or ambiguous external outcomes.

## Current interpretation rules

### Five-Agent quality evidence

Engineering/runtime completion is not the same as proof that Five-Agent execution is always superior to a bounded single-agent multi-pass baseline. If a resource-parity or judge gate is marked incomplete in `STATUS_MATRIX.md`, report that limitation explicitly rather than upgrading it to a quality claim.

### Production readiness

Treat supervised execution and autonomous unsupervised execution as separate claims. A supervised-production-ready status does **not** authorize unsupervised external publishing or autonomous production operation.

### Provider and model settings

Current provider definitions, cost policies, credential rules, fallback behavior, run-pinned snapshots, and local OpenAI-compatible behavior are determined by the executable code/tests at the checked-out commit. Older provider tables or certificates cannot override current registry/settings behavior.

### Test and certification claims

A PASS belongs only to the exact evidence that produced it. Before stating that current HEAD is certified, verify that the certification artifact names the current commit or rerun the relevant test/certification suite. A historical certificate for an older SHA is not evidence that newer HEAD has passed the same suite.

## Historical documents

The following documents may contain statements that were accurate at an earlier phase but are not current-state authority:

- `COLLABORATION_RUNTIME_GAP.md` — historical pre-runtime gap audit; explicitly superseded for current runtime status.
- `FINAL_CERT_VERDICT.txt` — certification evidence for the commit recorded inside that file only; it must not be generalized to a newer HEAD.
- Old benchmark/evaluation artifacts — valid for their recorded benchmark inputs, model/provider configuration, commit, and environment only.

Do not delete historical evidence merely because it is stale. Mark it historical/superseded and preserve it for auditability.

## Required behavior for future repairs

Before modifying architecture, governance, provider routing, or agent behavior:

1. Read this file.
2. Inspect current code and relevant tests.
3. Check `STATUS_MATRIX.md` and `ARCHITECTURE.md` for the latest recorded intent/state.
4. Identify whether any referenced certificate or benchmark is tied to current HEAD.
5. Make the smallest safe patch that fixes the verified defect.
6. Add deterministic regression coverage for the defect.
7. Do not weaken tests or rewrite frozen Five-Agent Brain/DNA prompts to solve an infrastructure bug.
8. Distinguish PASS, FAIL, ERROR, SKIP, flaky evidence, and untested state explicitly.

Last established: 2026-08-30.
