# Desktop UI Permission & Governance Model (UI_PERMISSION_MODEL.md)

## 1. Overview & Visual Governance Matrix

The UI must make security, permissions, and autonomy boundaries **immediately obvious, unambiguous, and tactile**. Power users should never wonder *"Will the agent automatically spend money or post without my approval?"*

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AUTONOMY MODE INDICATORS                        │
├─────────────────┬───────────────────────────────┬──────────────────────┤
│ 🔵 MANUAL       │ 🛡️ SUPERVISED (DEFAULT)       │ ⚡ AUTONOMOUS        │
├─────────────────┼───────────────────────────────┼──────────────────────┤
│ Amber Badge     │ Blue-Green Shield Badge       │ Purple Accent Badge  │
│ Every tool &    │ Low-risk runs autonomously;   │ Pre-approved budgets │
│ task halts for  │ High-risk (spend/publish)     │ & variants execute   │
│ manual sign-off │ halts for explicit 1-click 2FA│ within tight bounds  │
└─────────────────┴───────────────────────────────┴──────────────────────┘
```

---

## 2. Visual Risk Hierarchy in Chat & Modals

Every proposed action in the chat interface is tagged with a deterministic **Risk Tier Badge**:

| Risk Tier | UI Styling | Required Action | Example |
|---|---|---|---|
| **TIER 0: READ / REASON** | Slate / Cyan Pill | Executes automatically | *Scraping competitor ad library, analyzing JTBD* |
| **TIER 1: INTERNAL ASSET** | Violet Pill | Executes with inline status | *Generating 9:16 video storyboard, rendering voiceover* |
| **TIER 2: FINANCIAL SPEND** | Amber Warning Box | Halts pipeline → In-stream 2FA sign-off | *Allocating $500 ad spend to Meta campaign* |
| **TIER 3: LIVE MUTATION** | Red Alert Box | Halts pipeline → Double-confirmation modal | *Publishing ad creative live to production ad account* |

---

## 3. The Interactive Approval Interceptor Flow

When a Tier 2 or Tier 3 action is proposed by an agent (e.g. `PERFORMANCE` or `CMO`):

```text
1. [Agent proposes high-risk action]
        │
        ▼
2. [Central Chat Stream FREEZES downstream tasks]
        │
        ▼
3. [ApprovalRequestCard renders with glowing Amber/Red accent]
        │
   ┌────┴───────────────────────────────────────┐
   │                                            │
   ▼                                            ▼
[REJECT & FEEDBACK]                    [AUTHORIZE ACTION]
   │                                            │
   │ (User types reason:                        │ (User confirms budget/target)
   │  "Change CPA cap to $15")                  ▼
   ▼                                   [Cryptographic Audit Log Created]
[Agent revises parameters & restarts]          │
                                                ▼
                                       [Downstream pipeline unfreezes]
```

### Approval Card UI Elements:
- **Impact Summary Banner**: Bold currency / reach numbers (e.g., `+ $500.00 USD Budget`).
- **Target Channels & Entities**: Exact Ad Account ID, Campaign ID, and Product ID.
- **Diff / Parameter Inspector**: View exact JSON mutation payload.
- **Single-Click Authorization Button**: With keyboard shortcut (`⌘ + Shift + A` / `Ctrl + Shift + A`).
- **Reject & Revise Input**: Integrated micro-textarea allowing immediate instruction to the agent.

---

## 4. Live Agent Tool Access Toggles (In-UI Control)

Located in the **Right Inspector Panel (`TOOL_CONTROLS` tab)** or the **Agent Management Screen**, allowing the user to dynamically enable/disable individual tools per agent:

```text
┌────────────────────────────────────────────────────────┐
│ ⚙️ Tool Access Controller — Agent: PERFORMANCE         │
├────────────────────────────────────────────────────────┤
│ [🟢 ENABLED]  utm_builder                              │
│ [🟢 ENABLED]  analytics_aggregator                     │
│ [🟢 ENABLED]  component_attribution_engine             │
│ [🔴 DISABLED] live_campaign_publisher   (Safety Lock)  │
│ [🔴 DISABLED] budget_auto_scaler        (Safety Lock)  │
├────────────────────────────────────────────────────────┤
│ [ Save Tool Policy ]             [ Reset to Defaults ] │
└────────────────────────────────────────────────────────┘
```

---

## 5. Live Tamper-Evident Audit Stream

In the **Settings / Audit Tab** and bottom drawer:
- Displays streaming timestamped event logs matching `logs/audit_*.jsonl`.
- Each event row includes: `Timestamp` | `Agent` | `Product ID` | `Action Type` | `Autonomy Mode` | `Status (Approved/Rejected/Blocked)` | `Operator ID`.
