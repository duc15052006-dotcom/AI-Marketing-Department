# Tool Decision Matrix (TOOL_DECISION_MATRIX.md)

**Audit Date**: August 2026 (Updated: Phase 3B.1)  
**Scope**: Capability Mapping Across Marketing Intelligence Interfaces  
**Status**: ARCHITECTURAL DECISION MATRIX — ZERO CODE MODIFICATION IN THIS PHASE

---

## 1. Relative Routing Cost Classes

Routing decisions prioritize the lowest-cost reliable backend capable of satisfying the observation goal:

- **`COST_0_LIGHT`**: In-memory / pure HTTP GET (`httpx`, `trafilatura`, `beautifulsoup4`).
- **`COST_1_LOCAL_PARSE`**: Local CPU / Subprocess parsing (`yt-dlp` metadata/subtitles, RSS feeds).
- **`COST_2_BROWSER`**: Headless browser rendering (`Playwright Headless Chromium`, `Crawl4AI`).
- **`COST_3_AGENTIC_BROWSER`**: Autonomous multi-step LLM vision navigation (`Browser Use`).
- **`COST_4_EXTERNAL_METERED`**: Managed cloud scraping actors / paid APIs (`Apify Platform Actors`).

---

## 2. Updated Capability-to-Backend Decision Matrix

| CAPABILITY INTERFACE | PRIMARY BACKEND (COST CLASS) | FALLBACK BACKEND (COST CLASS) | DECISION | RATIONALE / WHY |
|---|---|---|:---:|---|
| **`search_web()`** | Direct HTTP Search / DuckDuckGo (`COST_0_LIGHT`) | Playwright Search Snapshot (`COST_2_BROWSER`) | **`WRAP`** | Direct HTTP search returns instant (<500ms) structured links without browser overhead. |
| **`read_page()`** | Trafilatura + HTTPX (`COST_0_LIGHT`) | Playwright Headless (`COST_2_BROWSER`) | **`USE` + `WRAP`** | 90% of content pages parse in <50ms via direct HTTP. Fall back to Playwright only when client-side JavaScript is mandatory. |
| **`analyze_url()`** | Direct HTTP + BeautifulSoup4 (`COST_0_LIGHT`) | Trafilatura Extractor (`COST_0_LIGHT`) | **`USE`** | Fast extraction of OpenGraph tags, meta descriptions, page titles, and schema.org JSON-LD without browser startup. |
| **`extract_structured_data()`** | Crawl4AI (`COST_2_BROWSER`) | Playwright DOM Evaluator (`COST_2_BROWSER`) | **`WRAP`** | Crawl4AI strips boilerplate and extracts structured Markdown/JSON for dynamic web pages. |
| **`youtube_metadata()`** | `yt-dlp` Native Engine (`COST_1_LOCAL_PARSE`) | YouTube oEmbed API (`COST_0_LIGHT`) | **`USE`** | Fast, reliable extraction of video titles, descriptions, upload dates, and channel details. |
| **`read_transcript()`** | `yt-dlp` VTT Extractor (`COST_1_LOCAL_PARSE`) | Direct Subtitle HTTP API (`COST_0_LIGHT`) | **`USE`** | Instant, zero-cost extraction of video speech transcripts in <1.0 second. |
| **`browser_navigate()`** | Microsoft Playwright (`COST_2_BROWSER`) | Direct HTTP (`COST_0_LIGHT` if static) | **`WRAP`** | Deterministic browser automation with full DOM inspection and screenshot capabilities. |
| **`browser_interact()`** | Microsoft Playwright Scripts (`COST_2_BROWSER`) | Browser Use (`COST_3_AGENTIC_BROWSER`) | **`WRAP`** | Prefer deterministic Playwright scripts for known flows; use Browser Use strictly as an exploratory fallback. |
| **`search_social()`** | Native Reddit/X Adapters (`COST_0_LIGHT`/`1`) | Apify Social Actors (`COST_4_EXTERNAL_METERED`) | **`WRAP`** | Native public endpoints handle initial scans; Apify serves as managed cloud fallback. |
| **`fetch_comments()`** | `yt-dlp` (YouTube) / Native Reddit (`COST_1`) | Apify Comment Actors (`COST_4_EXTERNAL_METERED`) | **`WRAP`** | Captures voice-of-customer feedback from public video and forum discussions. |
| **`observe_trends()`** | Google Trends RSS / Aggregators (`COST_0_LIGHT`) | Social Volume Monitors (`COST_1`) | **`WRAP`** | Lightweight RSS endpoints provide macro interest signals without heavy scraping. |
| **`analyze_competitor()`** | Composite (`analyze_url` + `read_page`) | Playwright Visual Auditor (`COST_2_BROWSER`) | **`WRAP`** | Multi-capability aggregation auditing landing pages, value props, and pricing structures. |
| **`inspect_product()`** | Crawl4AI E-Commerce Parser (`COST_2_BROWSER`) | Playwright Product Snapshot (`COST_2_BROWSER`)| **`WRAP`** | Extracts pricing, variants, and product specs into structured schemas. |
| **`download_authorized_media()`**| `yt-dlp` / Native HTTP Streaming (`COST_1`) | Local Media Cache (`COST_0_LIGHT`) | **`USE`** | Ingests authorized public creative assets strictly for internal AI semantic analysis (no copyright re-broadcasting). |
