# AI Marketing Department — UI Components Specification (UI_COMPONENTS.md)

## 1. Global Shell Components

### 1.1 Left Sidebar (`NavigationSidebar`)
- **Container**: `w-60 bg-slate-950 border-r border-slate-800 flex flex-col justify-between`
- **Top Brand Area**: Minimal brand glyph + workspace name + product switcher dropdown.
- **Primary Navigation List**:
  - `Chats` (Icon: MessageSquare, Badge: Unread / Pending approvals)
  - `Agents` (Icon: Bot, 5 active specialist status dots)
  - `Products` (Icon: Box, Active partition ID)
  - `Campaigns` (Icon: Target, Active spend tracker)
  - `Creative Studio` (Icon: Clapperboard, Rendering jobs badge)
  - `Knowledge` (Icon: BookOpen)
  - `Analytics` (Icon: BarChart3)
  - `Reports` (Icon: FileText)
- **Bottom Utilities**:
  - `Settings` (Icon: ShieldCheck, Mode: SUPERVISED indicator)
  - `User Profile / Workspace Status`

---

### 1.2 Top Bar (`GlobalTopBar`)
- **Container**: `h-13 bg-slate-900 border-b border-slate-800 px-4 flex items-center justify-between`
- **Left**:
  - Breadcrumb: `Workspace > Product: PROD-CRM-01 > Chat: Q3 Video Launch`
  - Active Channel/Agent Pill: `CMO Orchestrator` (with avatar badge)
- **Center / Status Indicators**:
  - **Model Context Pill**: `⚡ Model Router: Auto (e.g. Claude 3.5 Sonnet / GPT-4o)` (Click to override)
  - **Autonomy Mode Pill**: `🛡️ Mode: SUPERVISED` (Click to inspect policy)
  - **Active Pipeline State**: `● 2 Agents Running (Intelligence, Creative)`
- **Right**:
  - `Approval Queue` (Amber bell with pending count badge)
  - `Inspector Toggle` (Icon: PanelRightClose / PanelRightOpen)

---

### 1.3 Multimodal Input Console (`InputConsole`)
- **Container**: Floating card or pinned bottom bar with rounded borders and subtle glow on focus.
- **Top Quick Actions Bar**:
  - `[ + Attach Brief ]` (Uploads PDF/Docx/MD)
  - `[ 🌐 Analyze URL ]` (Ingests and analyzes competitor or product page)
  - `[ 🎯 Select Persona ]` (Tags specific target persona)
  - `[ ⚡ Target Agent: @CMO / @Creative / @Intelligence ]`
- **Text Area**: Auto-expanding input field (`min-h-12 max-h-48`) supporting markdown and slash shortcuts (`/plan`, `/research`, `/hooks`).
- **Right Controls**:
  - Model Router latency/status badge.
  - Send button with keyboard shortcut (`⌘ + Enter` / `Ctrl + Enter`).

---

## 2. Interactive In-Stream Chat Cards

### 2.1 User Message Card (`UserMessageCard`)
- Distinct styling (`bg-slate-800/80 border border-slate-700/60 rounded-xl p-4 ml-12`).
- Badges for attached files, analyzed product URLs, and target persona tags.

### 2.2 CMO Delegation Preview Card (`DelegationPreviewCard`)
- Visual flowchart of the orchestrated sub-tasks across the permanent agents:
```text
┌────────────────────────────────────────────────────────────────────────┐
│ 👑 CMO Orchestration Plan — TASK-20260816-01                          │
├────────────────────────────────────────────────────────────────────────┤
│ Objective: Launch Q3 Video Ad Batch targeting SMB Tech Founders        │
│                                                                        │
│ 1. [✓] INTELLIGENCE  ──> Analyze top 5 competitor video hooks on Meta  │
│ 2. [⏳] STRATEGIST    ──> Formulate 3 value angles & test hypotheses     │
│ 3. [ ] CREATIVE       ──> Generate 9:16 scripts & storyboards          │
│ 4. [ ] PERFORMANCE    ──> Prepare UTM taxonomy & $500 test spend       │
├────────────────────────────────────────────────────────────────────────┤
│ [ View Full Task Envelope ]               [ Approve Execution Plan ]   │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Research Result Card (`ResearchResultCard`)
- Synthesizes findings from the **Intelligence Agent**.
- Displays key metrics, competitor ad breakdowns, customer review sentiments, and verified citations.
- Includes **Epistemic Classification Bar**:
  - `3 Facts` (Green) | `8 Observations` (Blue) | `4 Inferences` (Purple) | `2 Hypotheses` (Amber).
- Action buttons: `[ Inspect Evidence Sources ]`, `[ Pass to Strategist ]`.

### 2.4 Strategy & Hypothesis Card (`StrategyResultCard`)
- Displays core positioning statement, target messaging hierarchy, and recommended test angles.
- Highlights the primary **Marketing Hypothesis**:
  - Target Metric: `3s View Rate (+25%)` | Rationale: `Pain-led spreadsheet agitation`.
- Action buttons: `[ Edit Strategy ]`, `[ Trigger Creative Engine ]`.

### 2.5 Creative Concept & Hook Card (`CreativeConceptCard`)
- Displays generated creative angles with hook variations:
  - **Hook 1 (Contrarian)**: *"Stop tracking leads on spreadsheets..."*
  - **Hook 2 (Direct Pain)**: *"Your sales team lost 4 deals this week..."*
  - **Hook 3 (Question)**: *"Why do 80% of CRM implementations fail?"*
- Displays estimated duration, emotional hook category, and target persona fit score.
- Action buttons: `[ Open Storyboard ]`, `[ Generate Full Scripts ]`.

### 2.6 Video Production Job Card (`VideoJobCard`)
- Live rendering and asset synthesis card:
  - Progress bar: `Asset Synthesis (75%)` → `Voice VO (Done)` → `Timeline Assembly (Done)` → `Rendering (42%)`.
  - Preview window with video player and aspect ratio toggle (`9:16` / `16:9`).
  - Word-level subtitle preview track.
- Action buttons: `[ Open in Creative Studio ]`, `[ Download MP4 ]`, `[ Request Re-cut ]`.

### 2.7 Approval Request Card (`ApprovalRequestCard`)
- **CRITICAL GOVERNANCE COMPONENT**: Displayed whenever a high-risk action is intercepted:
```text
┌────────────────────────────────────────────────────────────────────────┐
│ ⚠️ HIGH-RISK ACTION APPROVAL REQUIRED                                  │
├────────────────────────────────────────────────────────────────────────┤
│ Action: Mutate Ad Campaign Budget & Schedule Creative Variant          │
│ Agent: PERFORMANCE                                                     │
│ Product: PROD-CRM-01 (Nexus CRM)                                       │
│                                                                        │
│ • Campaign ID: CAMP-2026-004 (Meta Ads)                                │
│ • Budget Commitment: $500.00 USD (Daily Cap: $100.00)                 │
│ • Deployed Variant: VAR-012 (Hook: Contrarian Glitch, Format: 9:16)   │
│ • Autonomy Mode: SUPERVISED                                            │
├────────────────────────────────────────────────────────────────────────┤
│ [ ❌ Reject & Provide Feedback ]             [ ✅ Authorize & Deploy ] │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.8 Analytics & Component Attribution Card (`AnalyticsSummaryCard`)
- Summarizes experiment performance linking ROI directly to creative components:
  - `Hook-042 (Contrarian)`: CTR `3.4%` | CPA `$18.20` | ROAS `3.8x` (🏆 Winner)
  - `Hook-011 (Talking Head)`: CTR `1.2%` | CPA `$44.10` | ROAS `1.1x`
- Action button: `[ Extract Learning to Memory ]`.

### 2.9 Learning Summary Card (`LearningSummaryCard`)
- Displays newly distilled `Success Memory` or `Failure Memory` record.
- Shows sample size, p-value, confidence score (0.96), and scheduled re-test date.
- Action button: `[ Request Knowledge Promotion ]`.

---

## 3. Right Inspector Panel (`InspectorPanel`)

The Right Inspector Panel provides comprehensive governance and execution auditability **without exposing private model chain-of-thought**. It is structured strictly into verified, human-readable operational tabs:

```text
┌──────────────────────────────────────────────────────────────────┐
│ 🔍 INSPECTION & AUDIT COCKPIT                                    │
├───────────────────┬───────────────────┬──────────────────────────┤
│ DECISION SUMMARY  │ AGENT ACTIONS     │ EVIDENCE & SOURCES       │
├───────────────────┴───────────────────┴──────────────────────────┤
│ • Decision Summary: High-level executive synthesis & confidence  │
│ • Agent Actions: Executed steps, tool calls, and handoffs        │
│ • Tool Calls: Exact tool name, parameters, execution status      │
│ • Evidence: Citations, source URLs, raw observation snapshots    │
│ • Handoffs: Agent-to-agent task delegation envelopes             │
│ • Approvals: Sign-off status, risk score, operator authorizations │
│ • Errors: Traceable execution exceptions or data warnings        │
│ • Confidence: Calibrated score [0.0 - 1.0] and risk factors      │
│ • Final Rationale: Business justification and next steps         │
└──────────────────────────────────────────────────────────────────┘
```

### 3.1 Decision Summary Tab
- Displays the primary business objective, overall calibrated confidence score (`0.0 - 1.0`), identified risk factors, and final commercial rationale.

### 3.2 Agent Actions & Tool Calls Tab
- Shows executed actions, tool invocations (`web_search`, `utm_builder`, `storyboard_compiler`), input parameters, execution duration, and structured tool outputs.
- Explicitly captures multi-agent handoffs (`CMO -> Intelligence -> Strategist -> Creative -> Performance`).

### 3.3 Evidence & Sources Tab
- Ingested platform URLs, scraper snapshots, citation hashes, and verification status (`VERIFIED`, `UNVERIFIED`, `DISPUTED`).

### 3.4 Epistemic Hierarchy Breakdown
- Interactive tree grouping statements into `FACT`, `OBSERVATION`, `INFERENCE`, and `HYPOTHESIS`.
