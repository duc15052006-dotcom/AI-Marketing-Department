# Runtime Hardening + Validated Marketing Learning Backlog

## Purpose

This note converts the latest architecture review into an implementation backlog for the non-Brain workstream. The immediate goal is to make the codebase trustworthy enough to connect the components already built into one continuous system, then provide durable infrastructure that lets the department learn from real marketing outcomes without confusing stored text with validated knowledge.

The guiding principles are:

1. **One execution authority boundary.** Brain proposes; Runtime authorizes and dispatches.
2. **Unknown external outcome is not failure.** Ambiguous side effects must reconcile before retry.
3. **Knowledge is versioned evidence.** Content changes create new immutable versions and invalidate dependent decisions when necessary.
4. **Learning means tested outcomes.** Memory should accumulate evidence-linked hypotheses, experiments, outcomes, and applicability scope rather than merely agent-generated text.
5. **No rewrite.** Each defect/invariant remains a small RED-first branch/PR with targeted tests and full hermetic qualification.

## Ownership Boundary

### Runtime / Large Architecture owns

- Mission/Commitment lifecycle, authority, revisioning, durable persistence, and recovery.
- Canonical state transition enforcement.
- Knowledge integrity, immutable snapshots, hashes/chunks, authority thresholds, provenance, and invalidation plumbing.
- Typed `Decision` / `ActionIntent` transport into the execution plane.
- Unified execution authority gate before `ToolGateway`.
- Receipt/action/decision/approval/commitment lineage.
- Durable repositories, migrations, transactions, restart survival, leases, and reconciliation.
- Error taxonomy, retry policy, unknown-outcome handling, idempotency, and external-effect safety.
- Adapter contract tests for timeout, streaming, cancellation, error semantics, and provenance.
- Hypothesis/experiment/validated-learning storage contracts, lineage, indexing, and re-evaluation triggers.
- Decision dependency graph and stale-decision detection.
- Backend explainability read models and audit timeline.
- Routing telemetry and quality/cost instrumentation.

### Shared Runtime / Brain

Runtime persists and enforces contracts; Brain provides semantic intelligence for:

- hypothesis generation and interpretation;
- causal reasoning;
- strategy/replanning;
- experiment design;
- outcome interpretation;
- deciding which agent composition is semantically appropriate.

Runtime must never substitute deterministic infrastructure logic for those Brain responsibilities.

## Prioritized Backlog

| Priority | Architecture / hardening item | Runtime implementation | Completion evidence |
| --- | --- | --- | --- |
| **P0** | Mission / Commitment authority | Canonical transitions only; immutable identity/scope; immutable authority containers; changes require revisions | adversarial mutation/transition RED tests + full hermetic CI |
| **P0** | Canonical Mission State Machine | Central transition API; direct arbitrary state mutation fails closed; terminal authority preserved | invalid-transition matrix + same-state/idempotent controls |
| **P0** | Knowledge integrity | Content-addressed versions; new hash/chunks on content change; `min_authority`; snapshot/copy semantics | old/new content cannot alias; decisions pin exact knowledge version |
| **P0** | Decision / ActionIntent execution bridge | Carry decision/action IDs and authority context into `ToolRequest`; propagate lineage into receipt | Decision -> ActionIntent -> ToolRequest -> Receipt trace test |
| **P0** | Unified Execution Authority Gate | Single runtime boundary for scope, cancellation, commitment, permission, approval, budget, stop conditions, idempotency, safety | no consequential ToolGateway dispatch can bypass the gate |
| **P0** | Unknown outcome vs failure | Add explicit ambiguous outcome / reconciliation-required semantics | timeout-after-side-effect test proves no blind duplicate retry |
| **P0** | External-effect reconciliation | Reconcile external reality before retrying uncertain consequential actions | crash/timeout recovery tests preserve at-most-once or safe-idempotent behavior |
| **P1** | Durable Mission / Commitment repositories | Durable backend, migrations, transactions/version checks, restart survival | new store/process instance reloads identical authoritative state |
| **P1** | Crash/restart recovery | Restore mission/checkpoint/task/effect state and reconcile in-flight actions | kill-between-steps scenario resumes without state loss or duplicate dispatch |
| **P1** | Long-term Goal Profile infrastructure | Persist desired outcomes, metrics, known/missing data, budget, authority, decisions, stop/wait conditions | mission survives many wake cycles independent of chat/model session |
| **P1** | Durable wake + event/condition triggers | Time/event/condition/manual/retry/reconciliation wake sources with dedup/leases | duplicate trigger cannot execute same wake twice |
| **P1** | End-to-end continuity | Goal -> evidence -> decision -> approval -> execution -> receipt -> result -> checkpoint | one realistic workflow passes across process boundaries |
| **P1** | Error taxonomy + retry policy | transient/permanent/authorization/validation/cancelled/unknown-outcome classes | only retryable classes retry; ambiguous side effects reconcile first |
| **P1** | Decision dependency graph | Source -> claim -> decision -> action -> receipt -> result relations, initially SQLite-friendly | changed source can locate affected decisions/content |
| **P1** | Hypothesis Ledger infrastructure | Hypothesis, evidence refs, experiment, evaluation criteria, result, applicability scope, lifecycle | tested learning can be retrieved separately from unvalidated claims |
| **P1** | Re-evaluation triggers | Source expiry, changed goal, cost threshold, contradictory result, unavailable provider/tool | dependent decisions become `REVIEW_REQUIRED` instead of silently continuing |
| **P1** | Explainability backend | Structured read model for current work, evidence, uncertainty/status, budget, stop reason, pending approvals | UI can explain system state without exposing hidden chain-of-thought |
| **P1** | Runtime modularization | Split oversized orchestration/execution/verification/completion modules only after contracts stabilize | behavior-preserving refactor with existing and adversarial tests green |
| **P2** | Adapter contract suite | Shared contract tests across model/tool adapters | new providers satisfy timeout/error/stream/cancel/provenance contract |
| **P2** | Provider failure hardening | Rate-limit, timeout, interrupted stream, fallback and cancellation semantics | no provider failure can become fabricated success |
| **P2** | Dynamic routing infrastructure | Risk/data-gap/complexity/budget inputs + deterministic envelope + telemetry | routing decisions measurable by quality/cost; Brain owns semantic choice |
| **P2** | Quality/cost telemetry | token, latency, provider, agent-count, retries, external outcomes | multi-agent/provider choices can be evaluated from real data |

## Required Cross-Component Tests

The test strategy must expand from unit correctness to coordination correctness:

1. **Full flow:** goal -> evidence -> decision -> approval -> execution -> receipt.
2. **Recovery:** terminate the process mid-work, reopen, retain state, and avoid duplicate execution.
3. **Authority:** project/scope changes, approval revocation, cancellation, budget exhaustion before dispatch.
4. **Knowledge change:** decision pinned to version A remains attributable when version B arrives; dependent content becomes stale/review-required where appropriate.
5. **Provider failure:** rate limit, timeout, interrupted stream, cancellation; runtime never fabricates a successful outcome.
6. **Real-work completion evidence:** CI green must eventually be complemented by a realistic user workflow that produces traceable outputs and receipts.

## Validated Marketing Learning Infrastructure

### Long-term Goal Profile

Runtime persists, versions, and audits:

- desired outcome and measurable success criteria;
- available and missing evidence;
- budget and permitted action scope;
- decision references and reasons/structured evidence references;
- stop/wait/escalation conditions;
- wake/re-evaluation conditions.

Brain determines strategy; Runtime guarantees durability and authority.

### Hypothesis Ledger

The durable record should support:

- hypothesis statement;
- initial evidence references;
- experiment references;
- primary metric/evaluation rule, duration, and minimum-data requirements;
- status such as `PROPOSED`, `TESTING`, `SUPPORTED`, `REJECTED`, `INSUFFICIENT_DATA`, `STALE`;
- outcome references;
- applicability scope by product/audience/channel/time;
- confidence/evidence-quality metadata without claiming causality from correlation alone.

### Decision Dependency Graph

Start with stable IDs and relational edges; no graph database is required initially.

```text
KnowledgeSourceVersion
        -> Claim
        -> Decision
        -> ActionIntent
        -> AuthorizedAction
        -> ToolRequest
        -> ExecutionReceipt
        -> Outcome
```

When a source changes, runtime can locate dependent claims/decisions/content and mark them for review before another consequential dispatch.

### Re-evaluation Conditions

Important decisions may be reopened when:

- evidence/source expires or changes;
- user changes mission objective/scope;
- budget/cost crosses a threshold;
- observed result contradicts the linked hypothesis;
- required provider/tool becomes unavailable;
- reconciliation finds internal/external state divergence.

Runtime detects and schedules review; Brain decides the new semantic plan.

## Implementation Order

1. Finish Mission/Commitment authority and canonical lifecycle enforcement.
2. Harden knowledge integrity and knowledge-version dependency semantics.
3. Connect `Decision` / `ActionIntent` through one Execution Authority Gate to ToolGateway and receipt lineage.
4. Introduce explicit unknown-outcome + reconciliation-before-retry semantics.
5. Build durable repositories, migrations, restart recovery, and one full end-to-end continuity workflow.
6. Add Decision Dependency Graph + Hypothesis/Experiment/Outcome durable contracts.
7. Add re-evaluation triggers and explainability read model.
8. Standardize adapter contracts, error taxonomy, provider hardening, routing and quality/cost telemetry.
9. Refactor oversized modules only after the above behavioral contracts are stable.

## Current Proven Progress

The current stacked runtime work has already established several foundations, including Mission/Commitment binding, terminal Mission authority, Mission scope immutability, Commitment identity/scope immutability, explicit Commitment revisions, and deep authority-container immutability. These remain stacked Draft/Open/Unmerged PRs and are not considered merged into `main` until explicitly authorized.

This backlog is the authoritative non-Brain implementation direction for the current Large Architecture / Runtime Hardening workstream.