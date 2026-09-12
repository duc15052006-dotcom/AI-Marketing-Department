# AI Marketing Department — Source of Truth

This file defines how humans and AI coding agents must resolve conflicting repository documentation.

## Authority order

Use the following order from highest to lowest authority:

1. **Code and automated tests at the checked-out commit** — executable behavior and enforced invariants are authoritative for what the system currently does.
2. **Permanent system invariants in this file** — canonical identity, authority, provider, execution, and certification interpretation rules below.
3. **`ARCHITECTURE.md` and `AGENT_PROTOCOL.md`** — authoritative current architecture and collaboration contracts where they do not conflict with newer executable behavior or the invariants in this file.
4. **`STATUS_MATRIX.md`** — chronological implementation/evaluation history. Older phase rows remain valuable forensic evidence but are not current identity/provider/runtime configuration when a later migration superseded them.
5. **Phase-specific evaluation/certification artifacts** — valid only for the exact commit, benchmark, dataset, and environment they identify.
6. **Historical gap, planning, benchmark, or certification documents** — forensic history only. They must never override newer code, tests, canonical invariants, or exact-head certification evidence.

When two sources conflict, prefer the higher-authority source. Within the same tier, prefer the source tied to the newer verified commit/evidence. Never silently average contradictory claims.

## Permanent system invariants

- The department has exactly **5 permanent logical agents**: `CMO`, `Intelligence`, `Content`, `Creative`, and `Performance`.
- There is **no permanent Strategist agent and no Agent 6**. Historical `STRATEGIST` / `STRATEGY` inputs may exist only at explicit compatibility boundaries and must normalize to the canonical `Content` identity where the compatibility contract requires it.
- The CMO may appear at initial and final workflow stages but remains one logical CMO identity. Final CMO reuses CMO.
- **CMO** owns executive marketing strategy, positioning, GTM choices, major commercial trade-offs, resource/budget decisions, conflict resolution, and final commercial sign-off.
- **Intelligence** owns market/customer/competitor research, evidence acquisition, freshness verification, and explicit knowledge-gap reporting.
- **Content** owns evidence-grounded message architecture, copy/scripts, editorial/SEO planning, lifecycle messaging, content experiments, and channel adaptation.
- **Creative** owns visual/multimedia concepts, storyboards/shotlists, media specifications, rendering, and final image/video/audio asset production.
- **Performance** owns measurement, attribution, tracking, performance analysis, experiment observation, and governed paid-execution preparation/analysis.
- Brain/cognitive stages emit semantic intent and artifacts. Consequential external actions must cross governed runtime/tool/policy/approval boundaries; Brain identity alone never grants live publishing, spend, credential, or irreversible mutation authority.
- Preserve Human Approval / governed authority for consequential publishing, external-write, financial, credential, or high-risk actions. Never claim an action occurred without a truthful execution receipt/evidence.
- Provider/model choice is configuration-driven through the Universal Model Gateway / Provider Registry. Agent logic must not hard-code a provider dependency.
- Provider fallback is **explicit policy**, not implicit authority. An empty fallback chain means no fallback. A provider/model may be used only when enabled/configured and permitted by current cost/security policy.
- Provider cost governance must fail closed. Paid/unknown providers may not be silently treated as free.
- Security, provenance, approval, checkpoint, and receipt evidence must remain truthful even on failure or ambiguous external outcomes.
- Brain Learning / Collective Cognition or other frozen cognitive components must not be redesigned merely to repair infrastructure/documentation defects; require a concrete exact-head regression before changing frozen Brain behavior.

## Canonical six-stage cognitive flow

The permanent agent count remains five even though the supervised cognitive workflow can contain six stages:

1. **CMO (initial)** — objective, constraints, executive strategy frame, delegation.
2. **Intelligence** — grounded research/evidence and knowledge gaps.
3. **Content** — message/copy/content system from verified evidence and CMO-approved strategy.
4. **Creative** — visual/multimedia concept and production artifacts from the grounded content brief.
5. **Performance** — measurement/performance/experiment and governed execution planning.
6. **CMO (final)** — contradiction resolution, commercial governance, synthesis/sign-off.

Stage 6 is not a sixth agent.

## Current interpretation rules

### Legacy Strategist surfaces

A path, method, enum alias, serialized value, old benchmark, or historical phase record containing `strategist` is not proof of a permanent Strategist authority. Classify each occurrence before changing it:

- **CANONICAL** — current five-agent source; keep.
- **LEGACY-COMPATIBILITY** — required to read/normalize historical input; keep while it remains referenced.
- **LEGACY-HISTORICAL** — forensic benchmark/status evidence; mark non-authoritative rather than loading it as current identity.
- **MIGRATE** — valuable behavior belongs to a canonical owner and should be moved with provenance.
- **DELETE-CANDIDATE** — deletion requires exact-head reference/runtime/authority evidence, never name matching alone.

`STRATEGIST_EVALUATION.md` is a non-authoritative migration landmark. The historical 25-scenario benchmark is preserved by Git blob `e932320f28badb52bbb2dd968036debcb6ad87e5`; its executive-strategy coverage belongs to `CMO_EVALUATION.md` and its Content-owned cases belong to `CONTENT_EVALUATION.md`.

### `STATUS_MATRIX.md`

`STATUS_MATRIX.md` is chronological evidence accumulated across earlier phases. Rows naming the former Strategist identity, older default providers such as Gemini, or historical live-evaluation configurations describe those recorded phases only. They **must not** override current executable registry policy, the canonical five-agent identity above, or exact-head tests/certification. Future status updates should append a newer dated current-state section rather than rewriting forensic history without need.

### Five-Agent quality evidence

Engineering/runtime completion is not the same as proof that Five-Agent execution is always superior to a bounded single-agent multi-pass baseline. If a resource-parity or judge gate is incomplete, report that limitation explicitly rather than upgrading it to a quality claim.

### Production readiness

Treat supervised execution and autonomous unsupervised execution as separate claims. A supervised-production-ready status does **not** authorize unsupervised external publishing or autonomous production operation.

### Provider and model settings

Current provider definitions, cost policies, credential rules, fallback behavior, run-pinned snapshots, and local/custom OpenAI-compatible behavior are determined by executable code/tests at the checked-out commit. Older provider tables, historical live-provider results, or certificates cannot override current registry/settings behavior.

### Test and certification claims

A PASS belongs only to the exact evidence that produced it. Before stating that current HEAD is certified, verify that current HEAD itself passed the relevant acceptance suite. A historical certificate for an older SHA is not evidence that a newer HEAD passed the same suite.

## Historical documents

Documents may contain statements that were accurate at an earlier phase but are not current-state authority. Examples include:

- `COLLABORATION_RUNTIME_GAP.md` — historical pre-runtime gap audit.
- `FINAL_CERT_VERDICT.txt` — certification evidence only for the commit recorded inside it.
- historical rows inside `STATUS_MATRIX.md` — chronological phase evidence, not necessarily current configuration.
- old benchmark/evaluation artifacts — valid for their recorded benchmark inputs, model/provider configuration, commit, and environment only.

Do not delete historical evidence merely because it is stale. Mark it historical/superseded and preserve enough provenance for auditability.

## Required behavior for future repairs

Before modifying architecture, governance, provider routing, or agent behavior:

1. Read this file.
2. Inspect current code and relevant tests at exact HEAD.
3. Read `ARCHITECTURE.md` and `AGENT_PROTOCOL.md`; interpret `STATUS_MATRIX.md` chronologically rather than as a flat current-config table.
4. Identify whether any referenced certificate or benchmark is tied to current HEAD.
5. Make the smallest safe patch that fixes the verified defect.
6. Add deterministic regression coverage for the defect when the invariant can regress.
7. Do not weaken tests or rewrite frozen Brain/DNA prompts to solve an infrastructure/documentation bug.
8. Distinguish PASS, FAIL, ERROR, SKIP, flaky evidence, queued/pending CI, and untested state explicitly.
9. Never merge to `main` merely because a Draft integration PR is green; merging requires explicit human instruction.

Last canonical identity migration established: 2026-09-12.
