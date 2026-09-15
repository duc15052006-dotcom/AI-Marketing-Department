# Desktop UI Permission & Governance Model

## 1. Purpose

The UI must make a hard distinction between:

- **what an agent recommends or prepares**;
- **what current policy permits**;
- **what requires explicit human approval**;
- **what actually executed and has a truthful receipt**.

The permanent identities shown in permission/governance UI are exactly CMO, Intelligence, Content, Creative, and Performance. There is no permanent Strategist or Agent 6.

## 2. Automation/autonomy indicators

The product may expose modes such as `MANUAL`, `SUPERVISED`, or other configured automation levels, but the UI must never imply that a mode itself grants publish/spend/credential authority.

Recommended semantics:

| UI state | Meaning |
|---|---|
| **Manual** | User interaction is required for more internal steps than usual. |
| **Supervised** | Already-authorized low-risk internal cognition/tools may proceed; consequential actions still obey action-specific approval policy. |
| **Higher automation / autonomous label if supported** | Reduces repeated interaction only inside pre-existing trusted policy. It does **not** create new permission, spend caps, credentials, or bypass required approval. |

A badge may summarize automation posture, but the authoritative decision is always the current runtime/tool/policy/approval state for the specific action.

## 3. Risk presentation

Every proposed action should display a deterministic risk/authority state derived from backend policy rather than model prose.

Typical UX classes:

| Class | Example | UI behavior |
|---|---|---|
| **READ / REASON** | grounded research, internal analysis | may run when current tool/data/provider policy permits |
| **INTERNAL ARTIFACT** | copy draft, storyboard, internal render | show progress/result; does not imply publication |
| **EXTERNAL WRITE** | publish content, mutate live campaign | halt/request approval when required by current policy |
| **FINANCIAL** | initiate spend, change bid/budget | show exact amount/scope and enforce current budget/approval policy |
| **CREDENTIAL / SECURITY** | enable provider, change credential/security config | dedicated privileged settings flow; never ordinary agent self-approval |
| **DESTRUCTIVE / IRREVERSIBLE** | delete durable/live production state | strongest confirmation/approval required by current policy |

Exact tier names/enums come from current executable code; the UI must not invent a stronger permission model than the backend enforces.

## 4. Approval interceptor

When backend policy says an action requires approval:

```text
[Agent/Brain proposes semantic action]
        ↓
[Runtime/tool policy evaluates action]
        ↓
[Approval required]
        ↓
[UI shows Approval Request]
        ├── Reject / revise → no external execution
        └── Approve → backend revalidates authority/scope → execute → receipt
```

The UI must not “unfreeze” execution from a client-side button alone; backend policy must revalidate the action and approval state.

### Approval card requirements

Display, when applicable:
- action type and exact target entity;
- product/business/workspace scope;
- financial amount/budget delta;
- channel/account/campaign identifiers;
- sanitized parameter diff/payload summary;
- risk reason and relevant policy requirement;
- whether the action is reversible;
- idempotency/retry warning for uncertain external outcomes;
- approve/reject controls;
- final execution receipt status after backend execution.

Never show a model-generated “approved” phrase as equivalent to trusted approval state.

## 5. Agent/tool controls

Tool controls may enable/disable capabilities for canonical agents, but:

- installing/enabling a tool does not grant every action through that tool;
- agent identity does not bypass per-action permission/policy;
- credentials remain backend-only and should be represented by safe connection state, never raw secret values;
- changes to privileged provider/tool/security policy require the appropriate trusted settings authority;
- historical `STRATEGIST` compatibility identifiers must not render as a sixth permanent agent card.

Example conceptual UI:

```text
Tool Access — PERFORMANCE
  analytics_reader          enabled
  attribution_engine        enabled
  campaign_action_adapter   available, governed
  live write permission     determined per action by backend policy
```

## 6. Execution status truthfulness

The UI must distinguish at least these semantic states when relevant:

- proposed / drafted;
- validated / ready for approval;
- awaiting approval;
- rejected / blocked;
- executing;
- succeeded with receipt;
- failed;
- ambiguous / unknown external outcome.

Do not render “Published”, “Spend changed”, “Message sent”, or equivalent merely because a model claimed it or a request payload was prepared.

## 7. Audit view

The audit UI should expose sanitized, backend-derived evidence such as:
- timestamp;
- run/task/product/business identity;
- canonical agent/stage;
- action/tool/capability;
- policy/permission decision;
- approval reference/status;
- target entity and sanitized parameter diff;
- receipt/result status;
- ambiguity/failure reason;
- provider/tool provenance where material.

Do not label logs “cryptographically immutable” unless current implementation/tests prove that property at the viewed exact version.

## 8. Provider/settings UX

Provider/model settings should support the current provider-neutral architecture:
- enabled/disabled providers;
- global target and five canonical per-agent overrides;
- safe credential reference/input flow;
- custom OpenAI-compatible configuration where supported;
- explicit ordered fallback configuration;
- clear indication that an empty fallback chain means no fallback;
- test/save feedback without exposing secrets.

The UI must never create an implicit fallback chain or silently switch to a paid/unknown provider contrary to policy.

## 9. Fail-closed UX invariants

The UI is invalid if it:
- renders Strategist as a sixth permanent agent;
- suggests Final CMO is a separate permission principal;
- implies “Autonomous” automatically means publish/spend is authorized;
- allows client-side controls to bypass backend approval/security checks;
- exposes raw secrets;
- hides product/account/financial scope for consequential actions;
- conflates prepared/approved with executed;
- converts ambiguous external outcomes into success;
- suggests provider fallback exists when no explicit fallback policy is configured.

Backend code/tests and `SOURCE_OF_TRUTH.md` are authoritative over historical UI mockups or descriptions.