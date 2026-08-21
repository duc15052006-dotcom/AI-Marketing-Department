# Inter-Agent Communication Protocol (AGENT_PROTOCOL.md)

## 1. Core Principles of Agent Communication

The AI Marketing Department relies on rigorous, deterministic, and typed messaging between all agents. To prevent hallucination, misalignment, and uncontrolled cascades, every message and delegation must conform to the standard **Task Envelope**.

### 1.1 The Four Epistemic Tiers
Every claim, data point, or statement transmitted by an agent must be categorized into one of four epistemic tiers:

| Tier | Definition | Standard of Proof | Example |
|---|---|---|---|
| **FACT** | Ground truth verified by reliable internal records or primary empirical measurement. | Immutable system record, confirmed transaction log, or historical analytics report. | *"Product A's price is $49.00 with 1,240 orders in July."* |
| **OBSERVATION** | Direct sensory or scraped data captured from an external platform or public source. | Raw data payload, URL, timestamp, and scrape snapshot. | *"Competitor X launched 12 new video ads on Meta Ad Library on August 10."* |
| **INFERENCE** | Logical deduction or pattern derived by analyzing facts and observations. | Explicit reasoning chain linking known facts to the derived conclusion. | *"Competitor X is shifting focus toward UGC testimonials targeting working moms."* |
| **HYPOTHESIS** | An unproven assumption, prediction, or proposed experiment design. | Falsifiable prediction accompanied by a defined test condition and success metric. | *"If we test a 3-second problem-agitation hook, then 3s view rate will increase by 25%."* |

> **CRITICAL LAW**: Agents must **NEVER** present an Inference or Hypothesis as a Fact. Violations of epistemic categorization trigger automated validation rejection.

---

## 2. Standard Task Envelope Specification

All task requests, delegations, and deliverables between agents must wrap their payload inside the following typed schema.

```json
{
  "task_id": "TASK-20260816-001",
  "parent_task_id": null,
  "objective": "Identify top 3 competitor hooks in the B2B CRM space for Q3",
  "business_context": "Launching new sales automation feature targeting SMB founders.",
  "product_id": "PROD-CRM-01",
  "brand_id": "BRAND-NEXUS",

  "known_facts": [
    "Product retail price is $99/mo.",
    "Target audience is US founders with 5-50 employees."
  ],
  "unknown_facts": [
    "Exact ad spend of Competitor Alpha on TikTok Ads."
  ],
  "assumptions": [
    "Competitor Alpha runs their highest spending ads on Meta and YouTube."
  ],
  "hypotheses": [
    "Pain-point hooks highlighting 'lost sales leads' convert higher than feature-led hooks."
  ],

  "owner_agent": "INTELLIGENCE",
  "supporting_agents": ["STRATEGIST"],

  "tools_allowed": [
    "web_search",
    "social_ad_library_parser",
    "structured_data_extractor"
  ],
  "data_allowed": [
    "knowledge/marketing/hooks",
    "products/PROD-CRM-01/*"
  ],

  "evidence_required": true,
  "output_schema": "ResearchReport",
  "success_criteria": [
    "Minimum 5 validated competitor ads analyzed",
    "Hook breakdown classified into Hook Taxonomy",
    "Confidence score >= 0.80"
  ],

  "confidence": 0.85,
  "risks": [
    "Competitor ad library data may be geo-restricted."
  ],
  "blockers": [],

  "escalation_rule": "IF confidence < 0.70 OR evidence count < 3 THEN escalate to CMO",
  "next_action": "Pass validated ResearchReport to STRATEGIST for angle synthesis."
}
```

---

## 3. Envelope Field Definitions & Validation Rules

### 3.1 Task Identifiers & Context
- **`TASK_ID`**: Unique alphanumeric task identifier (Format: `TASK-YYYYMMDD-XXXX`).
- **`PARENT_TASK_ID`**: ID of the parent task if this is a subagent delegation; `null` for root tasks initiated by CMO.
- **`OBJECTIVE`**: Single, clear, unambiguous statement of work.
- **`BUSINESS_CONTEXT`**: Background rationale explaining *why* this task is being performed.
- **`PRODUCT_ID`**: Strict product workspace identifier. Enforces isolated data partition.
- **`BRAND_ID`**: Parent brand entity identifier.

### 3.2 Epistemic Declaration
- **`KNOWN_FACTS`**: List of verified facts relevant to this task.
- **`UNKNOWN_FACTS`**: Known gaps in information required to solve the task.
- **`ASSUMPTIONS`**: Working premises taken as true for the duration of the task.
- **`HYPOTHESES`**: Testable propositions formulated for experimentation.

### 3.3 Ownership & Access Controls
- **`OWNER_AGENT`**: The primary responsible agent (`CMO`, `INTELLIGENCE`, `STRATEGIST`, `CREATIVE`, `PERFORMANCE`).
- **`SUPPORTING_AGENTS`**: Secondary agents permitted to provide inputs or reviews.
- **`TOOLS_ALLOWED`**: Explicit whitelist of tools the agent may invoke.
- **`DATA_ALLOWED`**: Strict file and directory URI paths the agent is permitted to read. Any attempt to access paths outside this list is blocked.

### 3.4 Quality & Governance
- **`EVIDENCE_REQUIRED`**: Boolean flag. When `true`, no output is accepted without verifiable citations/sources.
- **`OUTPUT_SCHEMA`**: Target Pydantic/JSON Schema class expected in the deliverable.
- **`SUCCESS_CRITERIA`**: Deterministic checklist determining whether the deliverable is accepted.
- **`CONFIDENCE`**: Numerical float `[0.0 - 1.0]` representing agent certainty in the output.
- **`RISKS`**: Potential failure modes, data degradation risks, or brand risks.
- **`BLOCKERS`**: Active impediments preventing task completion.
- **`ESCALATION_RULE`**: Condition triggering automatic escalation back to CMO or Human Supervisor.
- **`NEXT_ACTION`**: Explicit downstream task or handoff protocol upon successful completion.

---

## 4. Agent Lifecycle & State Transitions

```
    [TASK CREATED]
          │
          ▼
   [VALIDATE INPUT] ──(Validation Failed)──> [REJECT / ESCALATE]
          │
          ▼
    [IN PROGRESS]
          │
    ┌─────┴────────────────┐
    ▼                      ▼
[EXECUTE TOOLS]    [COLLABORATE]
    │                      │
    └─────┬────────────────┘
          ▼
   [VALIDATE OUTPUT] ──(Schema or Criteria Fail)──> [REVISE or ESCALATE]
          │
          ▼
     [DELIVERED]
          │
          ▼
   [CMO SIGN-OFF] ──(Approved)──> [ARCHIVE TO MEMORY]
```

1. **Task Dispatch**: CMO constructs `TaskEnvelope` with validated schemas and permissions.
2. **Acceptance & Validation**: Target agent checks permissions, tool availability, and data bounds.
3. **Execution**: Agent performs reasoning and tool invocations within strict sandbox limits.
4. **Epistemic Classification**: Agent categorizes all findings into Fact, Observation, Inference, or Hypothesis.
5. **Output Verification**: Result is verified against `OUTPUT_SCHEMA` and `SUCCESS_CRITERIA`.
6. **Handoff / Escalation**: Deliverable passed to next pipeline stage or escalated if confidence falls below threshold.
