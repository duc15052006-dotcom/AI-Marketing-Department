# AI Marketing Department Strategic Roadmap (ROADMAP.md)

## Master Implementation Phases

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   PHASE 1    │ ──> │   PHASE 2    │ ──> │   PHASE 3    │ ──> │   PHASE 4    │
│  Agent Core  │     │ Core Skills  │     │  Knowledge   │     │ Observation  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                       │
┌──────────────┐     ┌──────────────┐     ┌──────────────┐             │
│   PHASE 8    │ <── │   PHASE 7    │ <── │   PHASE 6    │ <── ────────┘
│ Auto Publish │     │ Platform API │     │  Analytics   │     ┌──────────────┐
└──────────────┘     └──────────────┘     └──────────────┘     │   PHASE 5    │
       │                                                       │   Creative   │
       ▼                                                       │  Production  │
┌──────────────┐     ┌──────────────┐                          └──────────────┘
│   PHASE 9    │ ──> │   PHASE 10   │
│   Learning   │     │  Standalone  │
│  Evaluation  │     │ Application  │
└──────────────┘     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐
                     │   PHASE 11   │
                     │  Continuity  │
                     │    Runtime   │
                     └──────────────┘
```

---

### PHASE 1 — Agent Core & Foundational Architecture (CURRENT)
- [x] Initial directory topology and product workspace isolation.
- [x] Architecture specification (`ARCHITECTURE.md`).
- [x] Standard inter-agent communication envelope and epistemic protocol (`AGENT_PROTOCOL.md`).
- [x] Typed domain data schemas in Pydantic / Python (`DATA_MODEL.md` + `schemas/`).
- [x] Least-privilege security model & authorization gate specifications (`SECURITY_MODEL.md`).
- [x] Modular Creative Engine and video editing pipeline specifications (`CREATIVE_ENGINE.md`).
- [x] Dual-track continuous learning and memory model (`LEARNING_SYSTEM.md`).
- [x] Provider-agnostic model router interfaces and foundational unit tests.

---

### PHASE 2 — Core Marketing Skills Framework
- Define high-leverage atomic skills for each specialist agent:
  - **CMO**: Campaign orchestrator, budget allocator, brand compliance checker.
  - **Intelligence**: Competitor ad breakdown, review scraper, persona extractor.
  - **Strategist**: Value-prop matrix generator, hook strategy formulator, offer architect.
  - **Creative**: Hook copywriter, short-form scriptwriter, storyboard compiler.
  - **Performance**: UTM builder, ad variant matrix builder, metrics evaluator.
- Enforce strict typed inputs and structured outputs across all skills.

---

### PHASE 3 — Knowledge & Research Ingestion System
- Populate Tier 1 Global Knowledge Base:
  - Copywriting frameworks (AIDA, PAS, BAB, StoryBrand, Breakthrough Advertising).
  - Consumer psychology principles (Cialdini's influence, loss aversion, status signaling).
  - Platform algorithmic guidelines (TikTok, Reels, YouTube Shorts, Meta Feed).
- Implement semantic vector index and BM25 hybrid search over product documentation and brand files.

---

### PHASE 4 — Social Observation Layer (SOL)
- Build pluggable sensory adapters:
  - **Web Search & Scrape Gateway**: Brave Search / Google Search / Serper.
  - **Social Ad Library Scrapers**: Meta Ad Library, TikTok Creative Center.
  - **Structured Social Connectors**: TikHub / Apify MCP connectors.
  - **Browser Observation Fallback**: Headless Playwright/Puppeteer scraping sandbox.
- Implement epistemic validator enforcing raw citation capture and separation of observations from inferences.

---

### PHASE 5 — Creative Production Engine
- Implement modular generation adapters:
  - Image generation: Midjourney / Flux / SDXL adapters.
  - Video generation: Runway / Kling / Luma adapters.
  - Voice synthesis: ElevenLabs / OpenAI TTS / Local Kokoro / Bark.
  - Headless video assembly: Automated FFmpeg / MoviePy timeline renderer.
- Implement automated caption styling (karaoke subtitle generator) and audio normalization (-14 LUFS).
- Implement QA safe-zone validator for 9:16 vertical video formats.

---

### PHASE 6 — Analytics & Experiment Engine
- Build statistical attribution pipeline linking campaign performance to atomic creative tags.
- Implement automated statistical significance calculator (Bayesian & Frequentist A/B testing).
- Anomaly detection for ad fatigue, CTR decay, and CPC spikes.

---

### PHASE 7 — Platform API Gateway
- Build secure, token-isolated connectors for advertising networks:
  - Meta Marketing API (Campaigns, AdSets, Creatives).
  - TikTok Ads API.
  - Google Ads API.
- Implement two-phase commit transaction manager (`Validate` -> `Hold` -> `Execute`).

---

### PHASE 8 — Controlled Auto-Publishing & Autonomy Engine
- Implement the three-tier Autonomy Engine (`MANUAL`, `SUPERVISED`, `AUTONOMOUS`).
- Build human-in-the-loop approval webhooks (Slack/Discord/Email notifications with one-click sign-off).
- Enforce hard spending caps, automatic budget freeze on CPA anomalies, and rollback triggers.

---

### PHASE 9 — Continuous Learning & Evaluation System
- Implement automated distillation of campaign post-mortems into `Success Memory` and `Failure Memory`.
- Automated decay tracking for marketing insights older than 90 days.
- Knowledge promotion evaluation pipeline with Human/CMO sign-off gates.

---

### PHASE 10 — Standalone Enterprise Application
- Full-stack multi-brand dashboard (FastAPI backend + modern reactive frontend).
- Visual campaign timeline builder, live creative previewer, and experiment visualizer.
- Real-time agent collaboration chat and interactive Ask-Mentor cockpit.

---

### PHASE 11 — Persistent Worker / Continuity Runtime

**Goal:** turn the five-agent department from a session-bound workflow into a durable workforce that can own long-lived missions, sleep, wake, resume after restart, reconcile external reality, and execute consequential actions only through runtime-enforced authority.

**Boundary:** this phase is runtime/infrastructure hardening. It does not implement hypothesis generation, causal reasoning, strategy invention, replanning intelligence, or outcome interpretation inside the Brain.

#### 11.1 — Shared Contracts + Mission / Commitment Domain Model
- Add stable Brain ↔ Runtime contracts for `MissionContext`, `Observation`, `ActionResult`, `BudgetSnapshot`, `AuthoritySnapshot`, `ReconciliationFinding`, and `WakeEvent`.
- Add runtime contracts for `MissionRecord`, `CommitmentRecord`, `WakeRecord`, `TaskEnvelope`, `AuthorityDecision`, `BudgetReservation`, `ExternalEffectRecord`, `CheckpointState`, `RetryRecord`, and `ReconciliationRecord`.
- Make Mission and Commitment identity/scope immutable once activated.
- Fail closed: a mission cannot become executable without a canonical commitment bound to the same mission and authoritative scope.

#### 11.2 — Mission Control Plane
- Implement `MissionStore`, `MissionService`, `MissionStateMachine`, and mission leases.
- Durable lifecycle: `CREATED`, `READY`, `ACTIVE`, waiting/sleep states, then `COMPLETED`, `CANCELLED`, `FAILED`, or `EXPIRED`.
- Keep mission lifetime independent of chat session, model/provider process, and individual runtime runs.

#### 11.3 — Durable Wake Infrastructure
- Implement separate `DurableScheduler`, `EventBus`, `ConditionWatcher`, `WakeDispatcher`, and wake deduplication.
- Supported wake sources: time, external/internal event, condition threshold, manual wake, retry, reconciliation.
- Preserve the current dependency scheduler for intra-wake task ordering; do not conflate it with long-lived mission scheduling.

#### 11.4 — Mission Task Runtime
- Implement durable `MissionTaskQueue` with priority, dependency, lease, cancellation, retry metadata, and poison-task handling.
- Bridge mission tasks into the existing Five-Agent orchestrator and dependency-aware scheduler.
- Preserve exactly five specialist agents; Continuity Runtime is a control plane, not a sixth agent.

#### 11.5 — Checkpoint, Resume & Reconciliation
- Persist mission checkpoints independently of process memory.
- Validate checkpoint integrity and authoritative scope before resume.
- Implement deterministic recovery selection and missed-work detection.
- Reconcile internal state with external reality before retrying uncertain consequential actions.

#### 11.6 — Action Authority Fabric
- Route every consequential `ActionIntent` through cancellation, permission, approval, budget, idempotency, and execution-safety checks before `ToolGateway`.
- Runtime owns enforcement; the LLM/Brain cannot self-grant authority.
- Add durable budget reservation/commit/release semantics for money, token, API, and time limits.

#### 11.7 — Durable External Effect Safety
- Upgrade in-process/single-flight idempotency to cross-restart durable idempotency.
- Implement `ExternalEffectLedger` with intent identity, provider/tool request identity, receipt, outcome, reconciliation status, and retry eligibility.
- On ambiguous crash/restart outcomes, query external reality before deciding whether a retry is safe.

#### 11.8 — Durable Cognitive-State Infrastructure
- Runtime stores and versions `WorldModel`, `Plan`, `DecisionJournal`, `Experiment`, and `Experience` records with provenance and lineage.
- Brain owns semantic interpretation, beliefs, hypotheses, causal reasoning, experiment design, and replanning decisions.
- Reflection scheduling belongs to runtime; reflection reasoning belongs to Brain.

#### 11.9 — Reliability & Mission Observability
- Add timeout, bounded retry/backoff, leases, locks, dead-letter queue, recovery counters, and deterministic failure classes.
- Add mission timeline, wake history, task/action receipts, budget history, approval history, checkpoint lineage, reconciliation findings, and failure trail.
- Every wake and external effect must be traceable back to mission, commitment, authoritative scope, and originating decision/action intent.

#### Implementation order / hardening gates
1. Shared contracts + Mission/Commitment domain model.
2. Mission Store + lifecycle/state machine.
3. Durable wake system.
4. Mission task queue + existing scheduler integration.
5. Persistent checkpoint + resume + reconciliation.
6. Action Authority Fabric + durable external-effect safety.
7. Cognitive-state persistence + observability + reliability hardening.

Each runtime invariant is implemented as a small branch/PR with adversarial RED evidence before production code, targeted regression tests, then full hermetic CI. No Continuity Runtime PR may bypass existing cancellation, approval, provider, ToolGateway, lineage, checkpoint, or scope guarantees.