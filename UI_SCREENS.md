# AI Marketing Department — Application Screens Specification (UI_SCREENS.md)

## 1. Overview of Key Screens

The desktop application is divided into 7 primary screens, with the **Main Chat Screen** serving as the core default operational cockpit:

1. **Main Chat Screen** (Operating Command Center)
2. **Agent Management Screen** (The 5 Permanent Specialists & Tool Matrix)
3. **Product Workspace Screen** (Isolated Product Domains, USPs, Personas)
4. **Campaign Workspace Screen** (Campaign Trees, Experiment Roadmaps, Budgets)
5. **Creative Studio Screen** (Storyboards, Video Timelines, Asset Manifests)
6. **Analytics & Report Screen** (Component Attribution, ROAS/CPA, Research Reports)
7. **Permissions & Settings Screen** (Autonomy Modes, Guardrails, Audit Logs)

---

## 2. Detailed Screen Specifications

### 2.1 Main Chat Screen (Primary Cockpit)
- **Purpose**: Unified multi-agent conversation interface where all marketing workflows are initiated, tracked, reviewed, and approved.
- **Key Sub-Views & Layout**:
  - **Thread History Selector** (Left sub-panel or dropdown).
  - **Active Orchestration Feed** (Central stream showing messages, agent handoff nodes, and structured cards).
  - **Multimodal Input Console** (Bottom bar with file attachments, brief uploaders, Analyze URL action, and prompt field).
  - **Inspector Drawer** (Right panel syncing with active task: Decision Summary, Agent Actions, Tool Calls, Evidence, Handoffs, Approvals, Errors, Confidence, Final Rationale).
- **Core User Actions**:
  - Direct message to CMO or target specialist (`@creative`, `@intelligence`).
  - Drop campaign brief documents (PDF/Markdown) or paste competitor URLs (via `Analyze URL`).
  - Approve/Reject high-risk actions directly inline.
  - Expand deliverable cards to view raw schema payloads.

---

### 2.2 Agent Management Screen
- **Purpose**: View and manage the status, tool permissions, and operational health of the 5 permanent agents.
- **Components**:
  - **Agent Roster Grid**: Cards for CMO, Intelligence, Strategist, Creative, Performance.
  - **Agent Detail View**:
    - Agent identity & mission.
    - Active runtime status (`Idle`, `Reasoning`, `Awaiting Approval`, `Executing Tool`).
    - Tool Permission Matrix (toggle whitelisted tools on/off).
    - Model Routing override via Model Router (e.g. prioritize reasoning vs throughput models).
    - Recent task execution summary and error rate.
- **Constraints**: Shows strictly the 5 permanent agents. No arbitrary agent creation from this UI.

---

### 2.3 Product Workspace Screen
- **Purpose**: Manage multi-tenant product isolation and product-specific intelligence datasets.
- **Components**:
  - **Product Selector & Switcher**: Clean dropdown / list of isolated products (e.g., `PROD-CRM-01`, `PROD-ECOMM-02`).
  - **Product Profile Tab**: Core metadata, price models, target market, value propositions, features.
  - **Customer Persona Manager**: Active persona cards with jobs-to-be-done (JTBD), pain points, objection lists.
  - **Isolated Knowledge Browser**: Filesystem tree of product-specific research, past creatives, and experiment memory.
  - **Strict Partition Guarantee Badge**: Visual confirmation that active context is restricted to `products/{product_id}/`.

---

### 2.4 Campaign Workspace Screen
- **Purpose**: Monitor active and planned marketing campaigns, test structures, and budget allocations.
- **Components**:
  - **Campaign Hierarchy Tree**: `Campaign` → `Experiment` → `Creative Variants`.
  - **Budget Allocation Card**: Daily spend, allocated cap, total spent, pacing status.
  - **Hypothesis Tracker**: Active hypothesis statements linked to each campaign variant.
  - **Platform Sync Status**: Draft/Scheduled/Active state across connected ad accounts (under configured autonomy gate).

---

### 2.5 Creative Studio Screen
- **Purpose**: Deep visual inspection of creative concepts, hooks, scripts, storyboards, and video timeline manifests.
- **Components**:
  - **Concept & Hook Matrix**: Table of hooks categorized by hook type (Contrarian, Question, Direct Pain) with predicted vs actual CTR scores.
  - **Script Editor & Reviewer**: Structured view of scripts (Hook → Problem → Agitation → Solution → CTA).
  - **Storyboard & Scene Viewer**: Multi-column scene cards showing visual prompt, camera angle, on-screen text, voiceover script, and audio cues.
  - **Video Timeline Inspector**: Visual representation of the declarative `TimelineManifest` (layers for video, VO, BGM, subtitles, cuts).
  - **Asset Library**: Rendered video exports, image assets, and thumbnails tagged by component ID.

---

### 2.6 Analytics & Report Screen
- **Purpose**: Econometric analysis, creative component attribution, and research report library.
- **Components**:
  - **Component Attribution Heatmap**: Visual matrix showing ROAS, CPA, and CTR performance broken down by Hook ID, Angle, Editing Style, and CTA.
  - **Research Report Library**: Searchable repository of generated `ResearchReport` documents with clickable evidence links.
  - **Learning & Failure Log**: Visual dual-track memory browser (`Success Memory` vs `Failure Memory`).
  - **Export Center**: Clean PDF/Markdown report export.

---

### 2.7 Permissions & Settings Screen
- **Purpose**: Governance, security guardrails, autonomy policies, and audit logging.
- **Components**:
  - **Autonomy Mode Selector**: Radio toggle for `MANUAL`, `SUPERVISED` (Default), `AUTONOMOUS` with clear warning banners.
  - **Financial Guardrails**: Max daily spend limit ($), max auto-budget increase percentage (default 15%), 2FA phone/email settings.
  - **Model Provider Configuration**: Status of backend environment variables (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`) without exposing raw secret values.
  - **Tamper-Evident Audit Log Viewer**: Live tabular viewer for `logs/audit_*.jsonl` tracking all tool calls, approvals, and mutations.
