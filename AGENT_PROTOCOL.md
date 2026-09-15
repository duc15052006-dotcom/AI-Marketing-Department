# Inter-Agent Communication Protocol

## 1. Canonical participants

All permanent inter-agent communication is bounded to exactly five logical identities:

- `CMO`
- `INTELLIGENCE`
- `CONTENT`
- `CREATIVE`
- `PERFORMANCE`

There is no permanent `STRATEGIST` identity. Historical `STRATEGIST` / `STRATEGY` values may be accepted only by explicit compatibility code and must normalize to canonical `CONTENT` where the compatibility contract requires it. Final CMO is the same `CMO` identity reused at the final governance stage.

The protocol exists to prevent hallucination, authority drift, information loss, cross-workspace contamination, and uncontrolled action cascades.

---

## 2. Epistemic and provenance discipline

Material claims transmitted between agents must preserve their epistemic status and origin. Canonical concepts include verified/observed evidence, inference, hypothesis, and unknown/gap states. Exact executable enum names are defined by current schemas/runtime code.

Rules:
1. Never promote an inference or hypothesis to fact merely because a downstream agent repeats it.
2. Never fill an unknown with plausible prose.
3. Preserve source/citation/value origin for material claims and structured fields.
4. Surface contradictions instead of silently choosing one source.
5. Current external claims require fresh evidence when freshness is material.
6. Model recommendations are not binding constraints unless an authorized user/business/policy source makes them binding.

---

## 3. Standard task envelope

Task requests/delegations should carry the following semantics. Current executable schemas are authoritative for exact field names and serialization.

```json
{
  "task_id": "TASK-20260912-001",
  "parent_task_id": null,
  "objective": "Identify evidence-backed competitor messages in the B2B CRM category",
  "business_context": "CMO is evaluating Q4 positioning options for an SMB sales-automation product.",
  "product_id": "PROD-CRM-01",
  "brand_id": "BRAND-NEXUS",

  "known_facts": [
    "The active product is PROD-CRM-01."
  ],
  "unknown_facts": [
    "Which competitor message themes are currently repeated across verified ads and landing pages."
  ],
  "assumptions": [],
  "hypotheses": [
    "Pain-point messaging may be more prevalent than feature-led messaging."
  ],

  "owner_agent": "INTELLIGENCE",
  "supporting_agents": [],

  "tools_allowed": [
    "web_search",
    "read_page"
  ],
  "data_allowed": [
    "products/PROD-CRM-01/*"
  ],

  "evidence_required": true,
  "output_schema": "ResearchReport",
  "success_criteria": [
    "Material competitor claims have source lineage",
    "Unknown or unverifiable claims remain explicit gaps",
    "No cross-product evidence is introduced"
  ],

  "confidence": 0.0,
  "risks": [
    "Competitor pages may be geo- or time-dependent."
  ],
  "blockers": [],

  "escalation_rule": "Escalate material evidence gaps or strategic conflicts to CMO",
  "next_action": "Return verified evidence to CMO; downstream Content consumes CMO-approved strategic direction plus verified evidence."
}
```

The example is illustrative. It does not grant a tool, provider, permission, or schema field that current executable policy does not authorize.

---

## 4. Envelope semantics and validation

### 4.1 Identity and context
- **Task/run IDs** uniquely identify work and support provenance/idempotency.
- **Parent task ID** preserves decomposition lineage.
- **Objective** is a single unambiguous statement of work.
- **Business context** explains why the work matters without creating new facts.
- **Product/business/brand/workspace scope** must remain stable and must not be inferred from unrelated memory.

### 4.2 Knowledge state
- **Known/verified facts** require trusted evidence or authoritative internal records.
- **Unknown facts/gaps** remain unknown until evidence resolves them.
- **Assumptions/inferences** must remain labeled.
- **Hypotheses** must be falsifiable/decision-relevant when used for experiments.

### 4.3 Ownership
`OWNER_AGENT` must resolve to exactly one of:

```text
CMO | INTELLIGENCE | CONTENT | CREATIVE | PERFORMANCE
```

Role intent:
- `CMO`: executive strategy, prioritization, commercial trade-offs, conflict resolution, sign-off.
- `INTELLIGENCE`: research/evidence/freshness/knowledge gaps.
- `CONTENT`: message architecture, copy/scripts, editorial/SEO/channel content, semantic brief.
- `CREATIVE`: visual/multimedia concept and production.
- `PERFORMANCE`: measurement, attribution, observed performance, governed performance operations.

A supporting agent can advise or supply artifacts but cannot silently inherit the owner’s authority.

### 4.4 Tools and data
- Tool access is an explicit whitelist/capability decision, not implied by agent identity.
- Data access must preserve exact workspace/product scope.
- Missing tools/credentials/authority must fail closed where current runtime policy requires it.
- A tool being installed or registered does not imply permission to use it for the current run.

### 4.5 Quality and governance
As applicable, a handoff should include:
- acceptance/success criteria;
- evidence/citations and value origins;
- risks/blockers/unknowns;
- handoff target and next decision;
- measurement question;
- tool/approval requirements for consequential actions.

Confidence is never a substitute for evidence.

---

## 5. Canonical collaboration flow

The supervised cognitive flow contains six stages but five identities:

```text
CMO (initial)
   ↓
INTELLIGENCE
   ↓
CONTENT
   ↓
CREATIVE
   ↓
PERFORMANCE
   ↓
CMO (final; same identity)
```

### 5.1 CMO → Intelligence
Transmit objective, product/business scope, strategic questions, constraints, evidence requirements, and explicit unknowns. CMO does not dictate fabricated research conclusions.

### 5.2 Intelligence → CMO / Content
Intelligence returns verified evidence, source lineage, uncertainty, contradictions, and knowledge gaps. CMO owns strategic decisions derived from the evidence. Content may consume verified evidence together with CMO-approved strategic guardrails.

### 5.3 CMO → Content
CMO supplies target audience priorities, positioning/offer boundaries, business objective, non-pursuits, and material commercial constraints. Content must not self-grant missing executive decisions.

### 5.4 Content → Creative
Content supplies an actionable semantic brief: message hierarchy, copy/script, CTA, required proof, factual constraints, prohibited unsupported claims, channel/format needs, and experiment hypothesis/measurement question when applicable.

Creative owns visual concepts, storyboards/shotlists, media specifications, rendering, and final multimedia production.

### 5.5 Creative → Performance
Creative passes asset IDs/artifacts, production metadata, intended message/variant identity, and any unresolved production constraints. It must not invent performance conclusions.

### 5.6 Performance → final CMO
Performance returns observed metrics/evidence, attribution/causal caveats, experiment status, budget/risk implications, and governed execution readiness. It cannot self-approve forbidden spend/external writes.

### 5.7 Final CMO
The same CMO identity resolves contradictions, audits evidence/authority, chooses a commercial path, and produces the final governed synthesis. Final CMO is not Agent 6.

---

## 6. Constraint and information preservation

Handoffs must preserve material constraints structurally rather than relying on prose memory alone.

Never silently drop:
- user/system/business/brand/policy restrictions;
- product/workspace scope;
- explicit non-pursuits;
- evidence lineage;
- unknowns and unresolved contradictions;
- approval requirements;
- value/source origin required for auditability.

A downstream model suggestion must not become a binding constraint unless current authority policy permits that promotion.

---

## 7. Lifecycle and state transitions

```text
[TASK CREATED]
      ↓
[VALIDATE IDENTITY / SCOPE / INPUT / AUTHORITY]
      ├── invalid → [REJECT / ESCALATE]
      ↓
[BUILD GROUNDED CONTEXT]
      ↓
[REASON / PRODUCE SEMANTIC ARTIFACT]
      ↓
[VALIDATE OUTPUT / CLAIMS / HANDOFF]
      ├── fail → [REVISE / RESEARCH / ESCALATE]
      ↓
[DELIVER TO NEXT CANONICAL STAGE]
      ↓
[FINAL CMO GOVERNANCE WHEN REQUIRED]
      ↓
[GOVERNED RUNTIME / TOOL / APPROVAL PATH FOR CONSEQUENT ACTION]
      ↓
[TRUTHFUL RECEIPT / OUTCOME / LEARNING]
```

Completion of a cognitive task does not prove that an external side effect occurred.

---

## 8. Execution authority boundary

Agent prose, task ownership, or CMO sign-off does not by itself bypass runtime/tool/policy approval.

Consequential execution must preserve:
- canonical action/decision intent;
- run/task/product identity;
- permission/policy decisions;
- human approval where required;
- idempotency/retry semantics;
- provider/tool provenance where material;
- truthful success/failure/ambiguous-outcome receipts.

Never report “published,” “spent,” “changed,” or similar side effects solely because a model proposed or approved them.

---

## 9. Provider/model boundary

Task envelopes and permanent agent definitions must remain provider-neutral. Provider/model selection is resolved through current model policy/registry settings.

- Global target and per-agent overrides may be configured.
- Historical `STRATEGIST` model-policy keys may normalize to `CONTENT` at explicit compatibility boundaries.
- Fallback is allowed only when the ordered fallback policy is explicitly configured and current security/cost rules allow it.
- An empty fallback chain means no fallback.
- Run-pinned provider/model state should be preserved where current runtime requires reproducibility.

---

## 10. Fail-closed protocol invariants

A protocol/handoff fails review if it:
- names `STRATEGIST` as a current permanent owner/support authority;
- creates a sixth permanent agent or separate Final CMO identity;
- lets Content take final CMO strategy/sign-off authority;
- lets Creative own unsupported factual claims or authoritative measurement;
- lets Performance bypass approval/budget/policy boundaries;
- drops material constraints, evidence lineage, or workspace scope;
- increases epistemic certainty without new evidence;
- treats model text as proof of an external side effect;
- hard-codes a provider into permanent agent logic;
- introduces implicit fallback authority.
