# Security & Governance Model (SECURITY_MODEL.md)

## 1. Core Principles: Defense-in-Depth & Least Privilege

The AI Marketing Department operates under a strict Zero-Trust and Least-Privilege security architecture. Autonomous agents are powerful tools; left unrestricted, they present significant risks of data leaks, brand damage, runaway spending, and credential exposure.

### 1.1 Fundamental Security Invariants
1. **No Raw Secrets in Prompts**: API keys, OAuth tokens, and system credentials **never** enter agent context windows, prompt templates, or scratchpads.
2. **Backend Secret Management**: All credentials reside exclusively in isolated backend configuration environments (e.g., `.env`, Vault, or KMS-backed secret managers).
3. **Strict Capability Matrix**: No agent possesses universal authority. Each agent has hardcoded execution boundaries.
4. **Mandatory Audit Logging**: Every tool invocation, data read, state mutation, and external API call is recorded in an immutable, timestamped audit trail.

---

## 2. Agent Permission Matrix

| Agent | Read Research / Data | Create Strategy & Hypotheses | Generate Content Assets | Create Ad Accounts / Campaigns | Publish Content Live | Modify Budgets / Spend | Mutate Credentials / Config |
|---|---|---|---|---|---|---|---|
| **CMO** | ALL | Approves | Reviews | Approves | Approves Drafts | Approves Allocations | ❌ FORBIDDEN |
| **INTELLIGENCE** | Read Public & Allowed Product Data | ❌ | ❌ | ❌ | ❌ FORBIDDEN | ❌ FORBIDDEN | ❌ FORBIDDEN |
| **STRATEGIST** | Read Intelligence & Product Data | Author | ❌ | ❌ | ❌ FORBIDDEN | ❌ FORBIDDEN | ❌ FORBIDDEN |
| **CREATIVE** | Read Strategy & Product Data | ❌ | Author | ❌ | ❌ FORBIDDEN | ❌ FORBIDDEN | ❌ FORBIDDEN |
| **PERFORMANCE** | Read Campaign & Product Analytics | ❌ | ❌ | Prepares Payloads | Permitted via Autonomy Gate | Permitted under Strict Thresholds | ❌ FORBIDDEN |

### Agent-Specific Restrictions:
- **Research / Intelligence**: Sensory read-only. Cannot write to external platforms or trigger publishing actions.
- **Strategist**: Advisory and planning. Cannot directly execute ad buys or publish creatives.
- **Creative**: Generates assets and timeline manifests. Cannot directly publish to social channels or ad networks.
- **Performance**: The only agent equipped with platform dispatch tools, but gated strictly by the runtime autonomy policy.
- **CMO**: Strategic governor. Can review and approve or reject tasks, but possesses no raw credential manipulation tools.

---

## 3. Autonomy Modes & Policy Engine

The system supports three operational autonomy modes configured globally or per-product:

```
┌────────────────────────────────────────────────────────┐
│                     AUTONOMY MODES                     │
├─────────────────┬──────────────────┬───────────────────┤
│     MANUAL      │  SUPERVISED (Def)│    AUTONOMOUS     │
├─────────────────┼──────────────────┼───────────────────┤
│ Human must      │ Human approves   │ Agents execute    │
│ approve every   │ high-risk ops;   │ within strict pre-│
│ agent sub-task  │ low-risk runs    │ authorized budget │
│ & tool call     │ automatically    │ & risk boundaries │
└─────────────────┴──────────────────┴───────────────────┘
```

### 3.1 Mode Definitions
- **`MANUAL`**: All agent actions (including asset rendering, research queries, and plan finalizations) require human sign-off. Intended for initial onboarding and high-security compliance testing.
- **`SUPERVISED` (Default)**: Routine internal tasks (research, copy generation, storyboard rendering, internal metric analysis) execute autonomously. External actions (launching campaigns, modifying budgets, publishing live posts) halt and generate a `HumanApprovalRequest`.
- **`AUTONOMOUS`**: The system may automatically adjust budgets within predefined caps (e.g., ±15% daily spend) and publish pre-approved creative variants to active campaigns. Any anomaly triggers immediate rollback and downgrade to `SUPERVISED`.

---

## 4. Guardrails & High-Risk Authorization Gates

The backend Security Enforcement Gate automatically blocks execution and requires explicit human two-factor authorization for the following actions:

```
[Agent Action Proposed] 
          │
          ▼
   [Security Gate] ──(High-Risk Action Detected?)
          │                                  │
         NO                                 YES
          │                                  │
          ▼                                  ▼
   [Execute Tool]               [Freeze & Generate Approval Gate]
                                             │
                                    (Human Approves?)
                                       ├── YES ──> [Execute Tool]
                                       └── NO  ──> [Abort & Log Alert]
```

### High-Risk Trigger Categories:
1. **Financial Spend**: Any action initiating ad spend, committing budget, or modifying daily bid caps.
2. **Destructive Operations**: Deletion of creative assets, purging memory stores, dropping database tables, or resetting historical performance records.
3. **Credential & System Configuration**: Any attempt to modify API keys, rotate tokens, alter security thresholds, or reconfigure autonomy modes.
4. **Public Brand Actions**: Deleting live social media posts or publishing un-vetted media outside pre-cleared brand guidelines.

---

## 5. Multitenancy & Workspace Isolation

To prevent catastrophic data cross-contamination across brands and products:
- **Directory Jails**: Agents operating on `PROD-001` are restricted to the filesystem subtree `products/PROD-001/` and global shared knowledge.
- **Vector Search Partitioning**: All vector embeddings are tagged with `tenant_id`, `brand_id`, and `product_id`. Semantic similarity searches enforce strict metadata filtering.
- **Payload Sanitization**: Before passing data to any external tool or LLM, an automated sanitizer scrubs private customer PII (email, phone numbers, payment details).

---

## 6. Audit Logging Specification

Every event is written to append-only, tamper-evident logs under `logs/audit_YYYYMMDD.jsonl`:

```json
{
  "timestamp": "2026-08-16T19:41:00Z",
  "event_id": "EVT-89210",
  "agent": "PERFORMANCE",
  "product_id": "PROD-001",
  "action": "MUTATE_CAMPAIGN_BUDGET",
  "autonomy_mode": "SUPERVISED",
  "authorization": {
    "status": "APPROVED",
    "approver_id": "USER-ADMIN-01",
    "approval_timestamp": "2026-08-16T19:40:55Z"
  },
  "parameters": {
    "campaign_id": "CAMP-004",
    "delta": "+10%",
    "new_budget_usd": 550.00
  },
  "result": "SUCCESS"
}
```
