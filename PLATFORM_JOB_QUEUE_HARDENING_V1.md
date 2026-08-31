# Platform Batch #7 — Job Queue Hardening v1

## Purpose

Harden the existing `runtime.queue.RunManager` and `ResourceLimiter` for shared-platform use. This batch does **not** create a second queue, does **not** add a sixth agent, and does **not** wire new behavior directly into the five agent brains.

Dependency chain:

`#45 Plugin/MCP -> #49 Dynamic Tool Gateway -> #50 Connections/Secrets -> #51 Approval/Security -> Batch #7 Job Queue`

## Invariants added

### 1. Bounded admission and backpressure

`RunManager` now owns a bounded in-memory queue (`max_queue_size`, default `100`). Admission fails with `RUN_QUEUE_FULL` before reserving a new run ID when capacity is exhausted.

Enqueue admission is serialized separately from worker execution so concurrent producers cannot race each other into queue over-capacity or create reservation leaks.

### 2. Duplicate run integrity

A run ID already tracked by the manager cannot overwrite the existing `QueueItem`. Duplicate admission raises the existing canonical `RunIdAlreadyExistsError`.

The original run record and objective remain intact.

### 3. Explicit manager lifecycle

`RunManager.shutdown()`:

- stops new admissions;
- signals worker polling to stop;
- optionally marks queued/not-started runs cancelled;
- can wait for worker threads to terminate with a bounded timeout;
- does not silently force-kill an active canonical runtime execution.

Active-run cancellation remains an explicit `cancel_run()` operation.

### 4. Safer cancellation

Manager state is updated under the manager lock, but `runtime.cancel_run()` is called outside that lock. This avoids holding the queue lock across a potentially re-entrant runtime operation.

A queued run can be cancelled without dispatching the runtime at all.

### 5. Secret-safe failure state

Worker exceptions and runtime failure reasons are passed through the existing shared `governance.redaction.sanitize_sensitive_text()` boundary before they are stored or exposed by `QueueItem.model_dump()`.

No second redaction implementation is introduced.

### 6. Dynamic provider resource accounting

`ResourceLimiter` keeps the existing built-in limits for Xkiro, Gemini, web, and analytics, while supporting runtime registration/updates for additional providers.

Unknown plugin/MCP/custom providers no longer bypass resource accounting. They are automatically tracked with a conservative default concurrency limit of `1` unless explicitly configured otherwise.

## Intentionally deferred

This is still an in-memory queue. The following belong in a later durability/recovery batch rather than being mixed into queue-integrity hardening:

- persistent job repository;
- process-restart recovery;
- lease/heartbeat ownership;
- crash reconciliation for in-flight jobs;
- durable retry schedules;
- cross-process workers / distributed queueing.

Those features require a storage/recovery contract and should be validated independently.

## Validation

Focused regression coverage lives in:

`tests/test_platform_job_queue_hardening_v1.py`

It covers:

- duplicate run protection;
- bounded queue overload without run-ID reservation leakage;
- enqueue-after-shutdown rejection;
- worker shutdown/join behavior;
- pending-run cancellation on shutdown;
- queued cancellation without runtime dispatch;
- queue error secret redaction;
- conservative accounting of previously unknown providers;
- provider limit validation.
