# Open Source Tool Audit for Social & Web Observation (OPEN_SOURCE_TOOL_AUDIT.md)

**Audit Date**: August 2026 (Updated & Hardened: Phase 3B.1)  
**Auditor**: AI Marketing Department Architecture Team  
**Scope**: Open-Source, Official, and MCP Tools for Web, Social, Search, and Media Observation  
**Status**: ARCHITECTURAL AUDIT ONLY — ZERO PACKAGES INSTALLED IN THIS PHASE

---

## 1. Executive Summary & Core Principle

To provide the **Market & Consumer Intelligence Agent** with empirical observation capabilities without reinventing mature web crawling, browser automation, and social listening infrastructure, we conducted a verified primary audit of candidate open-source projects, official SDKs, and Model Context Protocol (MCP) ecosystems.

### Core Architectural Principle
External tools must never be tightly coupled to agent prompts or treated as monolithic black boxes. All external tool invocations pass through our:
`Agent` $\rightarrow$ `ObservationRouter` $\rightarrow$ `CapabilityRegistry` $\rightarrow$ `ToolGateway` $\rightarrow$ `Normalization Layer` $\rightarrow$ `Evidence/Provenance Ledger`.

---

## 2. Updated Candidate Evaluations

### 2.1 Microsoft Playwright (`playwright-python`)
- **Current Repository**: `microsoft/playwright-python` (GitHub)
- **Maintainer**: Microsoft Open Source Team
- **License**: Apache 2.0 (Commercially unencumbered)
- **Maintenance Status**: Highly active, regular monthly releases.
- **Windows / Python Support**: Native Windows 64-bit and Python (3.9–3.13+) support. Requires downloading browser binaries (~280MB for Chromium).
- **Primary Capabilities**: Deterministic headless browser automation (Chromium, Firefox, WebKit), full DOM snapshots, accessibility tree extraction, JavaScript execution, screenshot capture.
- **Resource Footprint**: `HEAVY` disk footprint (~350MB), `HIGH` memory usage (150–350MB per instance).
- **Decision**: **`WRAP`** — Primary Tier 4 deterministic browser backend (`browser_navigate`, `read_page` dynamic fallback).

---

### 2.2 Browser Use (`browser-use`)
- **Current Repository**: `browser-use/browser-use` (GitHub)
- **Maintainer**: Browser Use Inc / Gregor Zunic et al.
- **License**: MIT (Commercially permissive)
- **Maintenance Status**: Active; migrated to direct Chrome DevTools Protocol (CDP).
- **Windows / Python Support**: Native Python (>=3.11); supports local Chrome or cloud browser instances.
- **Primary Capabilities**: Autonomous goal-directed web interaction (navigating complex funnels, visual DOM grounding via vision/CDP).
- **Disallowed Upstream Capabilities**: All upstream stealth flags, CAPTCHA solvers, and fingerprint evasion are **strictly disabled** per `TOOL_SECURITY_POLICY.md`.
- **Resource Footprint**: `HEAVY` disk footprint, `HIGH` memory usage (300–600MB), high token consumption.
- **Telemetry**: Must set `ANONYMIZED_TELEMETRY="false"` in environment.
- **Decision**: **`WRAP`** — Tier 5 fallback backend strictly for complex exploratory browsing (`browser_interact`), NOT default for simple page reading.

---

### 2.3 Agent-Reach (Role & Provenance Correction)
- **Current Repository**: `Panniantong/Agent-Reach` (GitHub)
- **Maintainer**: Panniantong (Neo Reid) / Community Contributors
- **License**: MIT
- **Maintenance Status**: Active community scaffolding project.
- **Architectural Role Correction**: Agent-Reach is an **installer, configuration/diagnostic layer, and CLI bootstrap system** that delegates to individual upstream tools (e.g. `yt-dlp` for YouTube, `xreach` for Twitter, `gh` for GitHub). It is **NOT** a monolithic runtime social backend.
- **Production Adapter Strategy**:
  - `YouTube` $\rightarrow$ `IMPLEMENT_NATIVE_ADAPTER` (Direct `yt-dlp` Python wrapper; bypasses Agent-Reach CLI).
  - `Twitter / X` $\rightarrow$ `WRAP_SPECIFIC_UPSTREAM` (Targeted `xreach` wrapper or direct API/Apify).
  - `Reddit` $\rightarrow$ `IMPLEMENT_NATIVE_ADAPTER` (Direct HTTP `.json` endpoints; zero dependency).
  - `Instagram / TikTok` $\rightarrow$ `USE_STRUCTURED_PROVIDER` (Apify platform actors).
  - `Douyin / Bilibili / WeChat` $\rightarrow$ `DEFER` (Phase 4+).
- **Decision**: **`WRAP_SPECIFIC_UPSTREAM` / `DEFER`** — Agent-Reach serves as a reference and local diagnostic tool; our Tool Gateway implements stable native adapters for individual upstream tools.

---

### 2.4 Apify MCP Server & Platform Actors
- **Current Repository**: `apify/apify-mcp-server` (GitHub)
- **Maintainer**: Apify Technologies
- **License**: Apache 2.0 (MCP Server) / Hosted Platform Terms
- **Maintenance Status**: Actively maintained by Apify core engineering.
- **Architectural Role Clarification**: Apify is an **`OPTIONAL_MANAGED_STRUCTURED_EXTRACTION_BACKEND`**, not a "bot protection bypass layer".
- **Hosted MCP vs. Local Stdio MCP Comparison**:
  - **Hosted MCP (`https://mcp.apify.com/`)**: Remote HTTP/SSE; zero local installation; requires Bearer token; cloud network dependency.
  - **Local Stdio MCP (`npx @apify/actors-mcp-server`)**: Spawns local Node.js process; communicates via stdio JSON-RPC; requires local Node runtime.
- **Decision**: **`WRAP`** — Complementary structured cloud extraction backend in `ObservationRouter` for heavily bot-protected channels.

---

### 2.5 Official Model Context Protocol (MCP) Python SDK
- **Current Repository**: `modelcontextprotocol/python-sdk` (GitHub)
- **Package Name**: `mcp` (PyPI)
- **Maintaining Organization**: Model Context Protocol Project (Open community governance initiated by Anthropic)
- **License**: MIT
- **Current Stable Major**: `v2.x` (e.g. `2.0.0` supporting specification `2026-07-28`) with `v1.x` maintenance line (`mcp>=1.28,<2`).
- **Python Requirement**: Python `>= 3.10`.
- **Supported Transports**: `stdio`, `sse`, `streamable_http`.
- **Version Pinning Strategy**:
  - `MCP_SDK_MAJOR`: `2`
  - `MCP_SDK_VERSION_RANGE`: `">=2,<3"` (strict single-major version boundary)
  - `MCP_PROTOCOL_VERSION`: `"2026-07-28"`
  - `SDK_SUPPORTED_TRANSPORTS`: `["stdio", "sse", "streamable_http"]`
  - `GATEWAY_ENABLED_TRANSPORTS`: `["stdio", "sse"]`
- **Decision**: **`USE`** — Core protocol bridge in `ToolGateway` to connect external MCP servers alongside native Python tools.

---

### 2.6 yt-dlp (Scope Hardening)
- **Current Repository**: `yt-dlp/yt-dlp` (GitHub)
- **Maintainer**: yt-dlp Core Team
- **License**: The Unlicense (Public domain equivalent)
- **Allowed Capabilities**:
  1. `youtube_metadata` (title, description, duration, upload date, channel)
  2. `subtitle_discovery` (listing available human/auto subtitle tracks)
  3. `subtitle_retrieval` (downloading VTT/SRT subtitles)
  4. `automatic_subtitle_retrieval` (extracting auto-generated transcripts)
  5. `selected_comment_retrieval` (sampling top public comments for VoC analysis)
  6. `authorized_media_ingestion` (capturing public audio/video clips for internal AI analysis)
- **Explicit Exclusions**: Not an authoritative engagement analytics platform; zero automated reposting of copyrighted third-party video.
- **Decision**: **`USE` / `WRAP`** — Primary native Python engine for `read_transcript` and `youtube_metadata`.

---

### 2.7 Crawl4AI (Role & License Correction)
- **Current Repository**: `unclecode/crawl4ai` (GitHub)
- **Maintainer**: Crawl4AI Community (`unclecode`)
- **License**: Apache 2.0 with **Attribution Clause** (`LICENSE_CAVEAT = true`). Requires visible attribution badge/credit in documentation or product.
- **Architecture & Footprint**: Built on Playwright / Async Chromium. Classified under **`COST_2_BROWSER` / `BROWSER_ASSISTED_CRAWLING`** (not lightweight static HTTP).
- **Resource Footprint**: `HEAVY` disk footprint (~400MB with Playwright), `HIGH` memory usage (200–450MB).
- **Decision**: **`WRAP`** — Secondary smart extraction backend for JavaScript-heavy pages where clean Markdown/JSON is required.

---

### 2.8 Trafilatura & BeautifulSoup4
- **Current Repository**: `adbar/trafilatura` (GitHub) / `bs4`
- **Maintainer**: Adrien Barbaresi et al.
- **License**: Apache 2.0 / MIT
- **Resource Footprint**: `NEGLIGIBLE` (<10MB disk), `LOW` (<30MB memory).
- **Execution Cost Class**: `COST_0_LIGHT` (<50ms execution, zero browser overhead).
- **Decision**: **`USE`** — Primary Tier 1 & 2 lightweight HTTP extraction backend for `read_page` and `analyze_url`.

---

## 3. Revised 5-Tier Web Retrieval Hierarchy

```text
┌─────────────────────────────────────────────────────────────┐
│ TIER 1: Direct HTTP + Trafilatura / BS4 (COST_0_LIGHT)      │
│         Latency: <100ms | Footprint: Low | Tokens: 0        │
└──────────────────────────────┬──────────────────────────────┘
                               │ fallback if dynamic JS / blank
┌──────────────────────────────▼──────────────────────────────┐
│ TIER 2: Crawl4AI Browser-Assisted Crawl (COST_2_BROWSER)    │
│         Latency: 1.5s | Footprint: High | Tokens: 0         │
└──────────────────────────────┬──────────────────────────────┘
                               │ fallback if complex SPA / interactive
┌──────────────────────────────▼──────────────────────────────┐
│ TIER 3: Deterministic Playwright Script (COST_2_BROWSER)    │
│         Latency: 2.5s | Footprint: High | Tokens: 0         │
└──────────────────────────────┬──────────────────────────────┘
                               │ fallback if bot-protected cloud
┌──────────────────────────────▼──────────────────────────────┐
│ TIER 4: Apify Managed Cloud Actors (COST_4_EXTERNAL_METERED)│
│         Latency: 4.0s | Footprint: Low (Remote) | Tokens: 0 │
└──────────────────────────────┬──────────────────────────────┘
                               │ fallback if multi-step exploratory
┌──────────────────────────────▼──────────────────────────────┐
│ TIER 5: Agentic Browser Use (COST_3_AGENTIC_BROWSER)        │
│         Latency: 25s | Footprint: High | Tokens: High       │
└─────────────────────────────────────────────────────────────┘
```
