# Central Chat Workspace Specification & Wireframes (CHAT_WORKSPACE_SPEC.md)

## 1. Overview & Workspace Dynamics

The **Central Chat Workspace** is the core operational cockpit of the AI Marketing Department. It brings together conversational natural-language instruction, streaming multi-agent execution, structured interactive cards, and human-in-the-loop governance into a seamless desktop workspace.

> **Note on Model Providers**: Any model names shown in wireframes (e.g. Claude 3.5, GPT-4o) are **illustrative examples only**. The production interface connects exclusively via the provider-independent **Model Router**.

---

## 2. Master Desktop ASCII Wireframe

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [▲ AI Marketing Dept]  [Workspace: Nexus Corp] [Product: PROD-CRM-01 ▼] │ [Router: Auto (Example: Claude 3.5)] [🛡️ SUPERVISED]│
├──────────────────┬──────────────────────────────────────────────────────────────────────┬──────────────────────────────┤
│ 💬 CHATS         │ 👑 CMO Orchestration Thread: "Q3 Short-Form Video Campaign"          │ 🔍 INSPECTOR PANEL           │
│  • Q3 Video (●)  ├──────────────────────────────────────────────────────────────────────┤ [Decision Summary] [Evidence]│
│  • Comp Breakdown│ [USER] 10:14 AM                                                      │ [Tool Calls] [Handoffs/Logs] │
│  • Lead Magnet   │ Run a competitor hook analysis on Meta for B2B CRM tools, formulate  │                              │
│                  │ 3 positioning angles, and produce 2 short-form video concepts with   │ 🌿 Decision Summary          │
│ 🤖 AGENTS        │ storyboards. Allocate $500 initial test budget.                      │ • Status: In Execution       │
│  ● CMO (Active)  │ 📎 Attached: brief_q3.pdf   🌐 Target: competitor-crm.com            │ • Confidence: 0.92           │
│  ● Intelligence  │──────────────────────────────────────────────────────────────────────│ • Final Rationale: Pain hook │
│  ● Strategist    │ [CMO] 10:14 AM                                                       │   targets acute bottleneck.  │
│  ● Creative      │ ┌──────────────────────────────────────────────────────────────────┐ │                              │
│  ● Performance   │ │ 👑 CMO Orchestration Plan — TASK-20260816-01                     │ │ 🌿 Epistemic Breakdown       │
│                  │ │ 1. [✓] INTELLIGENCE  ──> Analyze & classify competitor hooks     │ │ ├─ [FACT] $99/mo Base Price│
│ 📦 PRODUCTS      │ │ 2. [✓] STRATEGIST    ──> Formulate 3 angles & test hypotheses    │ │ ├─ [OBSERVATION] 14 Meta Ad│
│  • Nexus CRM     │ │ 3. [✓] CREATIVE       ──> Build scripts & 9:16 storyboards       │ │ ├─ [INFERENCE] Pain vs Feat│
│  • Nexus Mobile  │ │ 4. [⏳] PERFORMANCE    ──> Awaiting budget sign-off ($500)        │ │ └─ [HYPOTHESIS] 3s Glitch  │
│                  │ └──────────────────────────────────────────────────────────────────┘ │                              │
│ 🎯 CAMPAIGNS     │                                                                      │ 📜 Evidence & Sources        │
│  • Q3 Growth     │ [INTELLIGENCE] 10:15 AM                                              │ Platform: Meta Ad Library    │
│                  │ ┌──────────────────────────────────────────────────────────────────┐ │ URL: meta.com/ads/lib/...    │
│ 🎨 CREATIVE      │ │ 🔍 Research Summary: 14 Competitor Ads Analyzed                  │ │ Ingested: 10:15 AM           │
│  • Studio & Cuts │ │ Top Angle: "Lost Sales Pipeline Panic" (64% share of voice)      │ │                              │
│                  │ │ [Epistemic: 3 Facts | 8 Observations | 3 Inferences]             │ │ ⚙️ Agent Actions & Tools    │
│ 📚 KNOWLEDGE     │ └──────────────────────────────────────────────────────────────────┘ │ • web_search: COMPLETED      │
│ 📊 ANALYTICS     │                                                                      │ • storyboard_gen: COMPLETED  │
│ ⚙️ SETTINGS      │ [STRATEGIST] 10:16 AM                                                │ • ad_publisher: HELD (Gate)  │
│                  │ ┌──────────────────────────────────────────────────────────────────┐ │                              │
│                  │ │ 💡 Strategic Angle: "The Spreadsheet Nightmare" (Pain-Agitation)  │ │ 🤝 Handoffs & Approvals    │
│                  │ │ Hypothesis: Glitch Hook will outperform feature demo by +30% CTR │ │ • Intelligence -> Strategist│
│                  │ └──────────────────────────────────────────────────────────────────┘ │ • Strategist -> Creative   │
│                  │                                                                      │ • Performance -> Human Gate  │
│                  │ [CREATIVE] 10:17 AM                                                  │                              │
│                  │ ┌──────────────────────────────────────────────────────────────────┐ │                              │
│                  │ │ 🎬 Creative Deliverable: 2 Video Concepts (9:16 Vertical)        │ │                              │
│                  │ │ • Concept 1: "Glitch Screen Panic" (Duration: 28s | Hook: 2.4s)  │ │                              │
│                  │ │ • Concept 2: "Founder 2 AM Regret" (Duration: 32s | Hook: 1.8s)  │ │                              │
│                  │ │ [ ▶️ Preview Storyboard ]               [ 🎞️ Render Manifest ]   │ │                              │
│                  │ └──────────────────────────────────────────────────────────────────┘ │                              │
│                  │                                                                      │                              │
│                  │ [PERFORMANCE / GOVERNANCE GATE] 10:18 AM                             │                              │
│                  │ ┌──────────────────────────────────────────────────────────────────┐ │                              │
│                  │ │ ⚠️ HIGH-RISK ACTION INTERCEPTED — APPROVAL REQUIRED              │ │                              │
│                  │ │ Agent: PERFORMANCE  |  Product: PROD-CRM-01                      │ │                              │
│                  │ │ Action: Commit $500.00 USD Ad Budget to Meta Ads Campaign        │ │                              │
│                  │ ├──────────────────────────────────────────────────────────────────┤ │                              │
│                  │ │ [ ❌ Reject & Revise ]             [ ✅ Authorize Spend ($500) ]  │ │                              │
│                  │ └──────────────────────────────────────────────────────────────────┘ │                              │
│                  ├──────────────────────────────────────────────────────────────────────┤                              │
│                  │ [ 📎 Attach File ] [ 🌐 Analyze URL ] [ 🎯 Target: @CMO ]            │                              │
│                  │ ┌──────────────────────────────────────────────────────────────────┐ │                              │
│                  │ │ Ask CMO to refine, launch, or re-run analysis... (⌘ + Enter)    │ │                              │
│                  │ └──────────────────────────────────────────────────────────────────┘ │                              │
└──────────────────┴──────────────────────────────────────────────────────────────────────┴──────────────────────────────┘
```

---

## 3. Multimodal Input Console Detailed Wireframe

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [ 📎 Attach File/Brief ]  [ 🌐 Analyze URL ]  [ 🎯 Target Persona: Tech Founder ]  [ @Agent: All ]   │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Launch A/B test comparing the Glitch Hook vs the Regret Hook on TikTok Ads targeting US Ops Leads...│
│                                                                                                      │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ 💡 Tip: Type /brief to insert template | Model Router: Auto Active                     [ 🚀 Send ↵ ] │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Key User Workflows in the Chat Workspace

### Workflow 1: Launching a Strategic Campaign Brief
1. User drops `brief.pdf` or enters an analyzed competitor link into the input console and specifies the goal: *"Create 3 video hooks for Q3 launch"*.
2. CMO parses the brief, validates against active `Product.id`, and renders `DelegationPreviewCard`.
3. Intelligence agent executes market analysis and renders `ResearchResultCard`.
4. Strategist agent formulates positioning angles and renders `StrategyResultCard`.
5. Creative agent generates word-level scripts and renders interactive `StoryboardCard`.
6. User reviews storyboard, inspects `Decision Summary` and `Evidence` in the Inspector Panel, and approves asset rendering.

### Workflow 2: Authorizing Ad Spend (Security Gate)
1. Performance agent stages campaign payload with tracking UTMs and $500 budget cap.
2. System intercepts outbound API request under `SUPERVISED` autonomy mode.
3. System renders `ApprovalRequestCard` in the chat stream with clear risk metrics.
4. User inspects parameters, tool calls, and final rationale in the Right Inspector Panel and clicks `[ ✅ Authorize Spend ]`.
5. System logs cryptographic audit entry to `logs/audit_*.jsonl` and initiates campaign deployment.
