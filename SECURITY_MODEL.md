# Security & Governance Model

## 1. Security principles

The AI Marketing Department uses defense-in-depth, least privilege, explicit authority, product/workspace isolation, and truthful execution evidence.

Core invariants:

1. **Exactly five permanent logical agents**: CMO, Intelligence, Content, Creative, Performance. There is no permanent Strategist and no Agent 6.
2. **Agent identity is not execution authority.** Brain/agents may reason and emit semantic intent, but consequential external effects require governed runtime/tool/policy/approval authority.
3. **No raw secrets in prompts or agent DNA.** Credentials are referenced through backend/provider/connection configuration and must not be serialized into ordinary model context or logs.
4. **Fail closed on missing authority.** Missing permission, malformed authority, unavailable approval, unknown provider cost, or uncertain external outcome must not be silently converted into success.
5. **Truthful receipts and provenance.** External writes/spend/publishing require execution evidence; model prose cannot prove that a side effect occurred.
6. **Strict product/business scope.** Retrieval, memory, tools, artifacts, and actions must not silently cross workspace/product boundaries.
7. **No implicit provider fallback.** Fallback is authorized only by explicit current model policy.

---

## 2. Canonical agent authority matrix

| Agent | Evidence / Data | Executive Strategy | Message / Copy / Editorial | Visual / Multimedia Production | Measurement / Attribution | Consequential External Action |
|---|---|---|---|---|---|---|
| **CMO** | May consume governed evidence | **Owns** strategy, positioning, GTM, major trade-offs, final commercial sign-off | Reviews / directs via Content | Reviews / directs via Creative | Reviews Performance evidence | **No direct bypass**; must use governed runtime/tool/approval path |
| **INTELLIGENCE** | **Owns** research/evidence acquisition within allowed scope | Advisory evidence only | No authority | No authority | No authoritative campaign outcome claim | Forbidden unless a separately governed observation/read tool is authorized |
| **CONTENT** | Consumes verified evidence | Must follow CMO-approved strategy; no final sign-off | **Owns** message architecture, copy/scripts, editorial/SEO/channel content | Semantic brief only; no final media-production authority | Proposes measurement questions/hypotheses only | No direct publish/spend/credential authority |
| **CREATIVE** | Consumes grounded brief/evidence constraints | No final strategy authority | Must preserve Content semantic/factual constraints | **Owns** visual/multimedia concept and production | No authoritative outcome claim | No direct publish/spend/credential authority |
| **PERFORMANCE** | Consumes campaign/analytics evidence | Advisory performance implications | No primary copy authority | No primary production authority | **Owns** measurement, attribution, observed performance analysis | May prepare/request governed actions but cannot bypass policy/approval/budget/credential gates |

Historical `STRATEGIST` / `STRATEGY` identifiers may exist only at explicit compatibility boundaries and must normalize to canonical `CONTENT` where required. They never grant independent permission.

---

## 3. Cognition versus side effects

The security boundary is structural:

```text
Agent / Brain reasoning
        ↓
Semantic intent / artifact
        ↓
Governed Runtime
        ↓
Capability / Tool Gateway
        ↓
Policy + permission + scope checks
        ↓
Human approval when required
        ↓
External adapter / system
        ↓
Truthful receipt: success | failure | ambiguous/unknown
```

No stage may skip directly from model text to an external write merely because the CMO or another agent “approved” it in prose.

---

## 4. Risk classes and approval

Exact executable risk/approval enums are defined by current code/tests. Conceptually:

### Read / observation / internal reasoning
Examples: bounded research, internal analysis, composing a draft, building an internal brief.

These may run automatically when current tool/data policy permits them. Read access must still honor product/business scope, network/tool policy, privacy, provider cost, and capability health.

### Internal artifact generation
Examples: copy draft, storyboard, internal media render, report, experiment plan.

These may be permitted by current policy but do not imply public publication or financial commitment.

### Consequential external write
Examples: publishing content, creating/modifying a live campaign, sending external messages, mutating production records.

Requires explicit governed action authority and any approval required by current policy. A prepared payload is not proof of execution.

### Financial / budget mutation
Examples: initiating spend, changing bids/budgets, committing paid resources.

Must be bounded by current budget/security policy and approval requirements. No permanent agent may self-grant a new spending limit.

### Credential / provider / security mutation
Examples: rotating keys, changing credential refs, enabling providers, altering security policy, changing privileged configuration.

Must remain outside ordinary agent self-authorization. Use dedicated settings/configuration authority and preserve auditability.

### Destructive / irreversible operation
Examples: deleting durable records, destructive production mutations, irreversible external actions.

Require the strongest applicable validation/approval and must fail closed on uncertainty.

---

## 5. Autonomy modes do not create authority

The product may expose labels such as Manual, Supervised, or other automation/autonomy settings. These settings control how much already-authorized low-risk work can proceed without repeated human interaction; they do **not** override action-specific security policy.

Hard rules:
- A mode cannot turn a forbidden action into an allowed action.
- A mode cannot create credentials, provider permission, spend authority, or public-publishing authority by itself.
- A mode cannot bypass an approval that current policy requires.
- “Pre-approved” is valid only when represented by current trusted policy/approval state, not by model text.
- If authority state is absent, malformed, expired, scope-mismatched, or ambiguous, fail closed.

This supersedes historical descriptions in which an `AUTONOMOUS` label alone appeared to permit agents to publish or alter budgets.

---

## 6. Secrets and provider security

- Store secrets in the configured backend/secret store or environment integration, never permanent agent prompts.
- Use opaque credential references where supported.
- Sanitize secrets from transport errors, logs, receipts, and serialized settings.
- Provider definitions must be enabled/configured and pass current security/cost policy before use.
- Custom/OpenAI-compatible base URLs must pass current validation policy.
- Paid/unknown providers must not silently execute in a policy mode that forbids them.
- Fallback candidates require explicit ordered configuration; an empty chain means no fallback.
- Run-pinned provider/model snapshots must remain immutable where required for reproducibility.

---

## 7. Workspace and data isolation

Every relevant artifact, retrieval, memory operation, tool request, and action must preserve canonical business/product/workspace scope.

Required properties:
- no cross-product memory/research leakage;
- exact/bounded retrieval scopes rather than accidental global reads;
- no model-generated scope widening;
- private/sensitive data minimization before external provider/tool transmission;
- explicit audit trail for any authorized scope transition.

A context mismatch is a security failure, not merely a quality issue.

---

## 8. Idempotency, retries, and ambiguous outcomes

External actions must use current idempotency/retry semantics so transport uncertainty cannot silently duplicate a consequential action.

If the system cannot prove whether an external action succeeded:
- record the outcome as ambiguous/unknown according to current receipt model;
- do not fabricate success;
- do not blindly retry when duplication is possible;
- require reconciliation/verification before a new irreversible attempt.

---

## 9. Audit and evidence

Audit records should preserve as applicable:
- run/task/product/business identity;
- canonical agent/stage;
- semantic action/decision intent;
- tool/capability/provider identity;
- permission/policy decision;
- approval record/reference;
- idempotency key;
- request/result status with secret sanitization;
- receipt/provenance/checkpoint identity;
- timestamp and failure/ambiguity reason.

Do not claim an immutable or cryptographic audit mechanism unless the exact implementation/test proves that property at current HEAD.

---

## 10. Security invariants for future changes

A change fails security review if it:
- restores Strategist as a permanent permission principal;
- creates a separate Final CMO permission principal;
- grants any agent universal tool/data authority;
- allows model prose to bypass runtime/tool/policy/approval checks;
- introduces implicit provider fallback or silent paid-provider execution;
- permits external publishing/spend solely because an “autonomous” mode is selected;
- exposes raw secrets in prompts, logs, serialized user-visible state, or receipts;
- weakens product/workspace isolation;
- turns ambiguous external results into success;
- removes provenance/idempotency/approval evidence required by current executable policy.

Current executable code/tests and `SOURCE_OF_TRUTH.md` override historical security/autonomy descriptions.