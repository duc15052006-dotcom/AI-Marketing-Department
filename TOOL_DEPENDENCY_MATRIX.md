# Tool Dependency & Runtime Footprint Matrix (TOOL_DEPENDENCY_MATRIX.md)

**Audit Date**: August 2026  
**Status**: ARCHITECTURAL AUDIT & DEPENDENCY GOVERNANCE — PHASE 3B.1  
**Scope**: Exact runtime dependencies, binaries, disk/memory classes across candidate tools.

---

## 1. Runtime Footprint Classification

To prevent uncontrolled dependency bloat on Windows 11, we strictly distinguish:
- **`SUPPORTED`**: Runs reliably on Windows 11 without kernel emulation or Linux layers.
- **`ZERO_DEPENDENCY`**: Pure Python library with zero external binaries, drivers, or cloud services.

### Classification Footprint Tiers
- **Disk Footprint Class**:
  - `NEGLIGIBLE`: $< 10\text{ MB}$ (pure Python wheels)
  - `LIGHT`: $10 - 50\text{ MB}$ (standard CLI wrappers)
  - `MODERATE`: $50 - 200\text{ MB}$ (complex libraries with bundled parsing wheels)
  - `HEAVY`: $> 200\text{ MB}$ (bundles headless browser binaries / Chromium)
- **Memory Footprint Class**:
  - `LOW`: $< 50\text{ MB}$ per process
  - `MODERATE`: $50 - 200\text{ MB}$ per process
  - `HIGH`: $> 200\text{ MB}$ per process (spawns headless browser or CDP instance)

---

## 2. Comprehensive Dependency Matrix

| CANDIDATE TOOL | WINDOWS_SUPPORTED | PYTHON_ONLY | REQUIRES_BROWSER_BINARY | REQUIRES_EXTERNAL_EXECUTABLE | OPTIONAL_FFMPEG | CLOUD_DEPENDENCY | DISK_FOOTPRINT_CLASS | MEMORY_FOOTPRINT_CLASS |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **`trafilatura`** | ✅ YES | ✅ YES | ❌ NO | ❌ NO | ❌ NO | ❌ NO | `NEGLIGIBLE` (<10MB) | `LOW` (<30MB) |
| **`beautifulsoup4` / `lxml`** | ✅ YES | ✅ YES | ❌ NO | ❌ NO | ❌ NO | ❌ NO | `NEGLIGIBLE` (<15MB) | `LOW` (<25MB) |
| **`httpx`** | ✅ YES | ✅ YES | ❌ NO | ❌ NO | ❌ NO | ❌ NO | `NEGLIGIBLE` (<5MB) | `LOW` (<20MB) |
| **`yt-dlp`** | ✅ YES | ✅ YES (or CLI) | ❌ NO | ❌ NO | ⚠️ YES (Media slicing) | ❌ NO | `LIGHT` (~30MB) | `LOW` (<40MB) |
| **`modelcontextprotocol` SDK** | ✅ YES | ✅ YES | ❌ NO | ❌ NO | ❌ NO | ❌ NO | `NEGLIGIBLE` (<5MB) | `LOW` (<25MB) |
| **`playwright-python`** | ✅ YES | ❌ NO | ⚠️ YES (Chromium ~280MB) | ❌ NO | ❌ NO | ❌ NO | `HEAVY` (~350MB) | `HIGH` (150-350MB) |
| **`Crawl4AI`** | ✅ YES | ❌ NO | ⚠️ YES (via Playwright) | ❌ NO | ❌ NO | ❌ NO | `HEAVY` (~400MB) | `HIGH` (200-450MB) |
| **`Browser Use`** | ✅ YES | ❌ NO | ⚠️ YES (Local Chrome / CDP) | ❌ NO | ❌ NO | ⚠️ Optional Cloud | `HEAVY` (~400MB) | `HIGH` (300-600MB) |
| **`Agent-Reach`** | ✅ YES | ❌ NO (Multi-tool CLI) | ❌ NO (Depends on tool) | ⚠️ YES (`xreach`, `gh`, etc.) | ❌ NO | ❌ NO | `MODERATE` (~100MB) | `MODERATE` (50-120MB) |
| **`Apify MCP Server`** | ✅ YES | ❌ NO (Node/NPX or SSE) | ❌ NO (Remote Cloud) | ⚠️ Node.js runtime (if stdio) | ❌ NO | ⚠️ YES (Apify Cloud) | `LIGHT` (~25MB) | `LOW` (<50MB) |

---

## 3. Dependency Minimization Strategy

1. **Eyes V0 Core Isolation**: The first operational slice of Eyes V0 (`search_web`, `read_page`, `analyze_url`, `youtube_metadata`, `read_transcript`) strictly uses `PYTHON_ONLY` and `NEGLIGIBLE`/`LIGHT` tools (`httpx`, `trafilatura`, `bs4`, `yt-dlp`).
2. **Delayed Browser Binary Installation**: Heavy browser binaries (`playwright install chromium`) are deferred to Phase 3D (Deterministic Browser Integration).
3. **No Docker / WSL Requirement**: All chosen packages run natively in standard Windows 11 PowerShell.
