# Persistent Worker / Continuity Runtime Architecture

## 1. Purpose

The Continuity Runtime converts the existing five-agent department from a session-bound workflow into a durable execution system that can own long-lived missions, sleep, wake, resume after process failure, reconcile external reality, and enforce authority before consequential actions.

This is a runtime/control-plane architecture. It does **not** add a sixth permanent agent and does **not** implement Brain reasoning such as hypothesis generation, causal inference, strategic replanning, marketing-task invention, or outcome interpretation.

## 2. Architectural Boundary

The system separates three concerns:

- **Brain:** decides what should happen next and emits typed proposals/intents.
- **Continuity Runtime:** persists responsibility, decides when work may wake, enforces authority, manages budgets/retries/idempotency, and guarantees recovery semantics.
- **Five-Agent Execution Plane:** executes bounded specialist work through the existing CMO, Intelligence, Strategist, Creative, and Performance topology.

The LLM is never the final authority for external side effects.

## 3. Target Topology

```text
User / Organization
        |
        v
     Mission
        |
        v
   Commitment
        |
        v
+---------------------------+
| Continuity / Mission      |
| Runtime Control Plane     |
|                           |
| Mission Store             |
| Commitment Store          |
| Mission FSM               |
| Wake / Resume Coordinator |
+-------------+-------------+
              |
   +----------+----------+
   |          |          |
   v          v          v
 Time       Event     Condition
Trigger      Bus       Watcher
   |          |          |
   +----------+----------+
              |
              v
           WakeEvent
              |
              v
      Context Assembler
              |
              v
            Brain
        "What next?"
              |
      typed contracts
              |
              v
      Mission Task Queue
              |
              v
 Existing Orchestrator /
 Dependency Scheduler
              |
              v
      Five Specialists
              |
              v
    Action Authority Gate
 cancellation / permission /
 approval / budget /
 idempotency / safety
              |
              v
          ToolGateway
              |
              v
       External Reality
              |
              v
   Effect Ledger + Results
              |
              v
     Reconciliation Engine
              |
              v
          Checkpoint
              |
         Sleep / Wake
```

## 4. Ownership Matrix

### Runtime-owned
- Mission lifecycle, store, service, state machine, and leases.
- Commitment persistence and enforcement metadata.
- Durable scheduler, event bus, condition watcher, wake dispatch/deduplication.
- Mission task queue, priorities, dependencies, leases, cancellation, retry metadata.
- Checkpoint persistence, validation, recovery selection, resume coordination.
- Durable idempotency and external-effect ledger.
- Reconciliation and missed-work recovery.
- Permission, approval, budget, cancellation, and execution-safety enforcement.
- Reliability primitives: timeout, bounded retry/backoff, locks, leases, dead-letter handling.
- Mission observability and audit trails.

### Shared Runtime / Brain
- `WorldModelStore`: runtime persists/version-controls; Brain owns semantic belief updates.
- `DecisionJournalStore`: runtime audits; Brain generates decision reasoning.
- `ExperimentStore`: runtime owns lifecycle; Brain designs experiments.
- `ExperienceStore`: runtime persists/indexes/retrieves; Brain derives lessons.
- Reflection: runtime schedules/records; Brain performs reflection.

### Brain-owned
- Hypothesis generation.
- Causal reasoning.
- Strategy and replanning intelligence.
- Marketing task invention.
- Outcome interpretation.

## 5. Shared Contracts

### Brain -> Runtime
- `Plan`
- `TaskProposal`
- `ExperimentProposal`
- `ActionIntent`
- `BeliefUpdate`
- `EscalationRequest`

### Runtime -> Brain
- `MissionContext`
- `Observation`
- `ActionResult`
- `BudgetSnapshot`
- `AuthoritySnapshot`
- `ReconciliationFinding`
- `WakeEvent`

### Runtime internal
- `MissionRecord`
- `CommitmentRecord`
- `WakeRecord`
- `TaskEnvelope`
- `AuthorityDecision`
- `BudgetReservation`
- `ExternalEffectRecord`
- `CheckpointState`
- `RetryRecord`
- `ReconciliationRecord`

Shared contracts must stay stable and typed so Brain work can evolve independently of runtime hardening.

## 6. Mission and Commitment

A Mission is a durable responsibility, not a chat turn or one `RuntimeContext` run. A Commitment binds that responsibility to runtime-enforceable authority and limits.

Canonical commitment data must cover at minimum:
- mission identity and authoritative business/project/user scope;
- allowed autonomy/authority envelope;
- deadlines/expiry;
- money, token, API-call, and time budgets when applicable;
- stop conditions;
- approval/escalation requirements;
- revision/version metadata.

A Mission must fail closed before entering executable lifecycle unless its active Commitment is present, canonical, and bound to the same Mission and authoritative scope.

## 7. Mission Lifecycle

```text
CREATED
   |
   v
READY
   |
   v
ACTIVE
   |
   +--> WAITING_FOR_TIME ------+
   +--> WAITING_FOR_EVENT -----+
   +--> WAITING_FOR_CONDITION -+--> ACTIVE
   +--> WAITING_FOR_APPROVAL --+
   +--> WAITING_FOR_RESULT ----+
   +--> SLEEPING --------------+
   |
   +--> COMPLETED
   +--> CANCELLED
   +--> FAILED
   +--> EXPIRED
```

Lifecycle transitions must be deterministic, auditable, and guarded by runtime invariants. Terminal states must never be revived implicitly.

## 8. Durable Wake Architecture

The current dependency-aware scheduler and the durable mission scheduler solve different problems:

- **Durable Mission Scheduler:** when a long-lived mission must wake again.
- **Dependency-aware Scheduler:** which bounded tasks execute before/after/in parallel during a wake cycle.

Wake sources:
- scheduled time;
- internal event;
- external event;
- condition/KPI threshold;
- manual/operator wake;
- bounded retry;
- reconciliation recovery.

Every wake carries a stable wake identity and must be deduplicated so duplicate event delivery cannot execute the same wake twice.

## 9. Wake Cycle

A wake cycle follows this control flow:

1. Acquire mission lease.
2. Load Mission + active Commitment + latest valid checkpoint.
3. Reconcile uncertain external effects before new consequential work.
4. Assemble `MissionContext`, authority snapshot, budget snapshot, observations, and prior outcomes.
5. Invoke Brain for typed proposals/intents only.
6. Validate and enqueue accepted mission tasks.
7. Execute through existing orchestrator/five-agent runtime.
8. Route every consequential `ActionIntent` through the Action Authority Gate.
9. Persist results, receipts, effect ledger, lineage, budget effects, and observations.
10. Write a durable checkpoint.
11. Compute next wake or terminal transition.
12. Release lease and sleep.

## 10. Action Authority Fabric

No consequential action goes directly from an LLM/agent to ToolGateway.

```text
ActionIntent
   |
   v
Cancellation check
   |
Permission / capability check
   |
Approval check
   |
Budget reserve/check
   |
Idempotency / effect check
   |
Execution safety check
   |
   v
ToolGateway
```

Runtime owns enforcement. The Brain may request or escalate authority but cannot grant it to itself.

## 11. Durable External-Effect Safety

In-process single-flight protection is insufficient for a worker that survives restarts. The runtime needs a durable `ExternalEffectLedger` that records:
- canonical action identity / idempotency key;
- mission/commitment/scope lineage;
- tool/provider request identity;
- execution state (`RESERVED`, `IN_FLIGHT`, `SUCCEEDED`, `FAILED`, `UNKNOWN`);
- receipt/result reference;
- reconciliation status;
- retry eligibility.

On restart after an ambiguous external call, runtime must reconcile external reality before retrying. This prevents duplicate posts, duplicate ad mutations, duplicate replies, and duplicated spend.

## 12. Checkpoint, Recovery, Resume

Continuity checkpoints extend current run checkpoints rather than bypassing them. Persistent recovery must:
- select only valid checkpoints for the same immutable authoritative scope;
- verify integrity before restore;
- preserve terminal cancellation/failure authority;
- restore task/wake/effect state needed for deterministic continuation;
- reconcile uncertain external actions before replay;
- never treat stale CI/process memory as durable truth.

## 13. Reconciliation Boundary

Reconciliation may deterministically detect facts such as:
- a scheduled publish time was missed;
- an external effect has no confirmed receipt;
- a provider reports an action already exists;
- internal and external state disagree.

Reconciliation does **not** invent marketing strategy. Semantic choices must be handled by an explicit deterministic policy, Brain decision, or human escalation.

## 14. Cognitive-State Persistence Boundary

Runtime may persist/version/index:
- World Model records;
- plans;
- Decision Journal entries;
- experiments;
- Experience Memory;
- evidence provenance and lineage.

Brain remains responsible for deciding what a belief means, whether a hypothesis is useful, what strategy should change, and what lesson should be learned.

## 15. Reliability Requirements

The Continuity Runtime must be designed against:
- process crash/restart;
- duplicate wake/event delivery;
- concurrent workers claiming the same mission/task;
- stale leases;
- retries after partially completed external actions;
- provider timeout/rate-limit/failure;
- cancellation racing with dispatch;
- expired approval or budget between planning and execution;
- poison tasks and repeated deterministic failure;
- stale checkpoints or mismatched authoritative scope.

Required primitives include bounded retry/backoff, timeout, lease/lock semantics, dead-letter handling, recovery counters, and explicit deterministic error classes.

## 16. Mission Observability

Every persistent mission must expose an auditable timeline linking:
- mission + commitment versions;
- wake reason and wake identity;
- Brain decision/proposal references;
- tasks dispatched to the five-agent runtime;
- approval and authority decisions;
- budget reservations/commits/releases;
- ToolGateway requests and execution receipts;
- external effects and reconciliation findings;
- checkpoints and resume lineage;
- failures, retries, cancellation, and terminal status.

## 17. Implementation Slices

1. Shared contracts + Mission/Commitment domain model.
2. Mission Store + lifecycle/state machine.
3. Durable Wake System.
4. Mission Task Queue + existing scheduler integration.
5. Persistent checkpoint + Resume + Reconciliation.
6. Action Authority Fabric + durable external-effect safety.
7. Durable WorldModel/Plan/Decision/Experiment/Experience storage.
8. Mission observability and reliability hardening.

Each production invariant is delivered as a small stacked branch/PR with adversarial RED evidence, targeted tests, full hermetic CI, and explicit artifact/digest evidence. No PR merges into `main` without explicit user authorization.