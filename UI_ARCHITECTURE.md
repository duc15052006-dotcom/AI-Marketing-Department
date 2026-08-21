# AI Marketing Department — Desktop UI Architecture (UI_ARCHITECTURE.md)

## 1. System Vision & Design Philosophy

The AI Marketing Department desktop interface is engineered as an **intelligent command cockpit** for power users (CMOs, Growth Leads, Founders, and Media Buyers) orchestrating a team of five autonomous AI marketing specialists.

### Core UI Principles:
1. **Chat-First Cognitive Center**: The conversation thread is the central operating plane. Everything—from strategic goal setting to creative storyboard reviews and budget approvals—originates and settles within the chat stream.
2. **Terminal Clarity, Modern Polish**: Minimalist, dark-mode native, high information density without clutter. Uses sharp visual hierarchy, muted slate backgrounds (`#0B0F17`, `#111827`, `#1F2937`), crisp typography (Inter / JetBrains Mono for data/logs), and subtle semantic accents (Emerald for success/fact, Amber for hypothesis/approval, Violet for creative, Blue for intelligence).
3. **Inspectable Autonomy Without Private CoT Exposure**: Every autonomous decision, agent handoff, epistemic tag, and tool call can be drilled into via the Right Inspector Panel. The UI strictly exposes structured operational metadata (**Decision Summary**, **Agent Actions**, **Tool Calls**, **Evidence**, **Handoffs**, **Approvals**, **Errors**, **Confidence**, **Final Rationale**) rather than raw model chain-of-thought.
4. **Zero Fluff**: No decorative consumer badges, no generic template carousels, and no disjointed dashboards that detach data from the strategic conversation.

---

## 2. Desktop Shell Architecture & Layout Grid

The desktop interface utilizes a 3-column + header layout optimized for standard 1080p, 1440p, and 4K desktop displays:

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                             TOP BAR                                              │
│ [Workspace: Nexus Corp] [Product: PROD-CRM-01]  │  [Model: Router (Auto)] [Mode: SUPERVISED 🛡️]   │
├──────────────┬────────────────────────────────────────────────────────────────────┬──────────────┤
│              │                                                                    │              │
│ LEFT SIDEBAR │                       CENTRAL CHAT WORKSPACE                       │ RIGHT PANEL  │
│              │                                                                    │ (INSPECTOR)  │
│ • Chats      │ • Primary conversation & multi-agent orchestration stream          │              │
│ • Agents     │ • Dynamic interactive cards (Research, Strategy, Creative, Perf)   │ • Decision   │
│ • Products   │ • Live agent delegation pipelines & task progress                  │ • Actions    │
│ • Campaigns  │ • In-stream approval gates & human sign-offs                       │ • Tool Calls │
│ • Studio     │                                                                    │ • Evidence   │
│ • Knowledge  │────────────────────────────────────────────────────────────────────│ • Handoffs   │
│ • Analytics  │                           INPUT CONSOLE                            │ • Approvals  │
│ • Settings   │ [ 📎 Attach ] [ 🌐 Analyze URL ] [ 🎯 Brief ]  [ Message CMO... ]   │ • Rationale  │
└──────────────┴────────────────────────────────────────────────────────────────────┴──────────────┘
```

> **Note on Model Integration**: The Top Bar and status indicators display the provider-independent **Model Router** context. Concrete model names (e.g. Claude 3.5, GPT-4o) in mocks represent routing examples only.

### Layout Grid Dimensions (Desktop Default):
- **Left Sidebar**: Fixed `240px` (collapsible to `64px` icon-only mode).
- **Central Chat Workspace**: Flexible `min 720px`, fluid scaling with max-width content container `960px` for optimal reading typography.
- **Right Inspector Panel**: Collapsible/Expandable `360px` - `480px` (drawer/sidebar mode) for deep inspection of tasks, raw JSON payloads, epistemic trees, and approval manifests.
- **Top Bar**: Fixed `52px` height, sticky global status bar.

---

## 3. High-Level Subsystem Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                             DESKTOP APPLICATION                              │
├────────────────────────────────────────────────────────────────────────────────┤
│ 1. ROUTING & SHELL                                                             │
│    ├── Navigation Controller (Sidebar & View Switching)                        │
│    ├── TopBar Status Engine (Model Context, Autonomy Mode, Workspace Switcher) │
│    └── Inspector Manager (Right Panel Context Synchronization)                 │
├────────────────────────────────────────────────────────────────────────────────┤
│ 2. CHAT & STREAMING ENGINE                                                     │
│    ├── Multi-Agent Message Streamer (SSE / WebSocket Protocol)                 │
│    ├── Interactive Card Renderer (Structured Custom Message Types)             │
│    ├── Delegation Pipeline Visualizer (Live Agent-to-Agent Handoffs)           │
│    └── Input Console (Multimodal upload, URL parser, Command Palette)          │
├────────────────────────────────────────────────────────────────────────────────┤
│ 3. INSPECTION & GOVERNANCE COCKPIT                                             │
│    ├── Epistemic Breakdown Viewer (Fact, Observation, Inference, Hypothesis)   │
│    ├── Evidence & Source Inspector (Raw JSON, Citations, Crawl Snaps)          │
│    ├── Tool & Permission Controller (Live Tool Toggles, Rate Limits)           │
│    └── Approval Gate Interceptor (2FA Sign-off, Budget Spend Authorization)    │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Interaction & Event Model

1. **User Prompt Dispatch**: User sends goal to CMO with attachments or product URLs (via `Analyze URL`).
2. **CMO Plan Broadcast**: CMO responds with a reactive `DelegationPreviewCard` outlining sub-tasks assigned to Intelligence, Strategist, Creative, and Performance.
3. **Parallel Task Execution Stream**: Central chat displays agent execution steps with streaming live status pills (`Intelligence: Analyzing competitor ad library... [OK]`).
4. **Interactive Deliverable Cards**: As agents finish deliverables, structured interactive cards render inline (e.g., `StrategyCard`, `StoryboardCard`, `VideoRenderCard`).
5. **Right Inspector Synchronization**: Clicking any card or pill opens structured decision summaries, tool calls, source citations, confidence metrics, and final rationales in the Right Panel.
6. **Approval Interception**: High-risk actions (e.g., ad spend allocation or live publishing) freeze the pipeline and render an `ApprovalCard` with clear impact metrics.
