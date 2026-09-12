# AI Marketing Department Architecture

## 1. Executive summary

The AI Marketing Department is a governed, provider-neutral, five-agent marketing system. It separates cognition from consequential execution, preserves evidence/provenance across handoffs, and keeps permanent authority bounded to exactly five logical identities.

The architecture enforces:

- **Exactly five permanent agents** with explicit role boundaries.
- **One CMO identity reused at initial and final governance stages**; there is no sixth Final CMO agent.
- **Evidence-grounded cognition** with explicit unknowns/hypotheses rather than fabricated certainty.
- **Provider-neutral model routing** through the Universal Model Gateway / Provider Registry.
- **Explicit fallback policy**; no provider/model fallback is authorized merely because another provider exists.
- **Workspace/product isolation**, lineage, durable artifacts/checkpoints, and truthful receipts.
- **Governed execution**: Brain/agents produce semantic intent; runtime/tool/policy/approval layers control consequential external effects.

---

## 2. Exactly five permanent agents

```text
                         ┌─────────────────────────────┐
                         │             CMO             │
                         │ Strategy + Orchestration    │
                         └──────────────┬──────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
              ▼                         ▼                         ▼
      ┌───────────────┐         ┌───────────────┐         ┌───────────────┐
      │ INTELLIGENCE  │         │    CONTENT    │         │   CREATIVE    │
      │ Evidence /    │         │ Message /     │         │ Visual /      │
      │ Research      │         │ Copy / Brief  │         │ Multimedia    │
      └───────┬───────┘         └───────┬───────┘         └───────┬───────┘
              │                         │                         │
              └─────────────────────────┼─────────────────────────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │   PERFORMANCE    │
                              │ Measure / Learn  │
                              └──────────────────┘
```

Historical `STRATEGIST` / `STRATEGY` names are not permanent identities. Where old serialized/model-policy inputs must remain readable, compatibility code may normalize them immediately to canonical `CONTENT`. A compatibility alias or deprecated method name never grants independent authority.

### 2.1 CMO — executive strategy and governance

**Owns:**
- executive marketing strategy and strategic prioritization;
- positioning and GTM choices;
- commercial trade-offs and explicit non-pursuits;
- resource/budget allocation decisions;
- cross-agent contradiction resolution;
- approval-ready synthesis and final commercial sign-off.

**Does not own:**
- primary market evidence acquisition;
- primary copy/editorial production;
- final visual/multimedia production;
- authoritative campaign measurement/attribution;
- direct ungated publishing, spend, credential mutation, or irreversible tool execution.

### 2.2 Intelligence — evidence and research

**Owns:**
- market/customer/competitor/category research;
- source discovery and evidence acquisition;
- freshness/reliability checks;
- customer language, objections, JTBD evidence, and category observations;
- explicit knowledge gaps and contradictory-source reporting.

**Boundary:** Intelligence supplies evidence; it does not self-grant final positioning, commercial sign-off, or downstream production authority.

### 2.3 Content — semantic/content layer

**Owns:**
- message architecture and content strategy within CMO-approved positioning/offer guardrails;
- copy, hooks, scripts, CTA wording;
- editorial planning, SEO briefs, lifecycle messaging;
- channel-native content adaptation and repurposing;
- content experiment hypotheses and semantic briefs for Creative.

**Boundary:** Content does not choose company-wide GTM/budget trade-offs, manufacture evidence, render final multimedia assets, self-certify measured winners, or execute live external actions.

### 2.4 Creative — visual/multimedia production

**Owns:**
- visual concepts and art direction within the grounded brief;
- storyboards, shotlists, image/video/audio production specifications;
- image/video/audio generation and final multimedia synthesis when an authorized production tool is available;
- visual consistency, production feasibility, and media-level variants.

**Boundary:** Creative does not invent strategic positioning/product proof, take over Content copy authority, certify performance outcomes, or publish externally without governed execution authority.

### 2.5 Performance — measurement and governed performance operations

**Owns:**
- tracking/measurement architecture;
- attribution and analytics;
- performance interpretation with causal/measurement caveats;
- experiment observation and decision evidence;
- paid-media/performance planning and governed execution preparation;
- feedback of observed outcomes to learning/cognition.

**Boundary:** Performance cannot bypass budget, policy, approval, credential, or external-write gates. Observed outcomes outrank guesses; correlation must not be promoted to causal fact without support.

---

## 3. Canonical six-stage supervised cognitive flow

There are six workflow stages but still only five permanent agents:

```text
1. CMO (initial)
   objective + constraints + executive strategy frame + delegation
        ↓
2. INTELLIGENCE
   evidence + provenance + unknowns + research findings
        ↓
3. CONTENT
   message architecture + copy/scripts + semantic/creative brief
        ↓
4. CREATIVE
   visual/multimedia concepts + production artifacts
        ↓
5. PERFORMANCE
   measurement + performance/experiment analysis + governed execution plan
        ↓
6. CMO (final; same CMO identity)
   contradiction resolution + commercial governance + final synthesis/sign-off
```

A stage handoff must preserve material constraints, evidence lineage, unknowns/hypotheses, product/workspace identity, and authority boundaries. Final CMO is a reuse of CMO, not Agent 6.

---

## 4. Cognition versus execution authority

The permanent agents/Brain reason about what should happen. They do not obtain external side-effect authority simply by emitting a recommendation.

Consequential actions flow through governed seams such as:

```text
Agent/Brain semantic intent
        ↓
Canonical action/decision intent
        ↓
Governed Runtime
        ↓
Tool/Capability Gateway
        ↓
Policy + permission + approval checks
        ↓
External action adapter
        ↓
Truthful execution receipt / ambiguous-outcome record
```

Required properties:
- fail closed when authority is missing or malformed;
- preserve idempotency/provenance/checkpoint semantics;
- never report success solely from model prose;
- separate “designed/approved/prepared” from “actually executed”;
- require human/policy approval where current governance demands it.

---

## 5. Provider-neutral model architecture

Agents do not hard-code a model vendor. Model invocation is mediated by the Universal Model Gateway and Provider Registry.

Canonical configuration concepts include:
- global provider/model target;
- per-agent overrides for the five canonical agents;
- enabled/disabled provider definitions;
- custom OpenAI-compatible provider configuration;
- credential references rather than plaintext secret serialization;
- run-pinned provider/model snapshot where required for reproducibility;
- capability/cost/security policy;
- ordered fallback chain that is effective **only when explicitly configured**.

An empty fallback chain grants no fallback authority. Historical provider choices, live-evaluation providers, or old documentation do not become current defaults merely because they once passed a benchmark. Current executable registry/settings code and exact-head tests are authoritative.

---

## 6. Product, brand, knowledge, and memory isolation

Every run must preserve its immutable business/product/workspace scope. Retrieval and writes must not silently cross tenant/product boundaries.

Knowledge/memory may include global and scoped tiers, but access must be explicit and auditable. Historical learning is not automatically truth: promotion requires the current evidence/learning policy, and stale or context-mismatched material must not override verified current facts.

Cross-product contamination is a hard failure condition.

---

## 7. Collaboration contract

Inter-agent communication uses typed/structured handoffs as defined in `AGENT_PROTOCOL.md` and executable schemas/runtime code.

A material handoff should preserve as applicable:
- task/run/product/brand identity;
- objective and constraints;
- verified evidence/citations;
- unknowns, inferences, and hypotheses;
- source/value origin and provenance;
- owner and allowed downstream authority;
- acceptance criteria and measurement questions;
- approval/tool requirements for consequential actions.

No downstream agent may increase epistemic certainty or execution authority merely by rewriting upstream prose.

---

## 8. Dynamic specialists and external harness integration

The platform may use dynamic/ephemeral specialists, plugins, skills, or external compatible agent/harness ecosystems, but they do not expand the permanent authority set.

Rules:
1. Permanent logical identities remain the canonical five.
2. Ephemeral specialists have bounded task scope and a canonical parent/authority owner.
3. They inherit workspace/security/approval constraints.
4. Their outputs are evidence/artifacts for the canonical system, not an independent permanent executive chain.
5. External harness/provider integration occurs through adapters/protocols rather than hard-coding agent logic to one vendor/tool ecosystem.

---

## 9. Observation and action integration layers

Observation/search/read capabilities may feed Intelligence through governed capability/tool interfaces. Platform actions may support ads, CMS, email, social, or other external systems, but live writes must remain behind current policy/permission/approval/receipt mechanisms.

Never infer “autonomous publishing is allowed” from the existence of an adapter.

---

## 10. Evaluation and learning

Evaluation is split by canonical ownership:
- `CMO_EVALUATION.md` — executive strategy/governance and migrated legacy strategy benchmark coverage.
- `CONTENT_EVALUATION.md` — Content truthfulness/semantic boundaries plus migrated Content-owned legacy cases.
- `INTELLIGENCE_EVALUATION.md`, `CREATIVE_EVALUATION.md`, `PERFORMANCE_EVALUATION.md` — specialist quality within their respective boundaries.
- collaboration/Brain/runtime tests — cross-agent preservation, cognition, provenance, authority, durability, and fail-closed behavior.

`STRATEGIST_EVALUATION.md` is legacy/non-authoritative. The former 25-scenario Strategist benchmark remains recoverable by blob `e932320f28badb52bbb2dd968036debcb6ad87e5`; useful behavior has canonical ownership rather than a revived Strategist agent.

Learning must preserve provenance, failed experiments, uncertainty, and causal caveats. A model-generated suggestion does not become durable organizational truth without satisfying current promotion/evidence rules.

---

## 11. Architecture invariants for future changes

Any future change fails architectural review if it:
- introduces a sixth permanent agent;
- restores Strategist as independent authority;
- turns Final CMO into a distinct permanent identity;
- moves executive strategy/sign-off out of CMO without an explicit architecture migration;
- merges Content and Creative authority in a way that loses truthful semantic/production boundaries;
- hard-codes provider logic inside permanent agent behavior;
- introduces implicit fallback authority;
- bypasses governed runtime/tool/approval controls for consequential action;
- weakens product/workspace isolation, provenance, checkpoint integrity, or truthful receipts;
- rewrites frozen Brain behavior to repair a non-Brain documentation/infrastructure defect without concrete regression evidence.
