# AI Marketing Department Strategic Roadmap (ROADMAP.md)

## Master Implementation Phases

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   PHASE 1    │ ──> │   PHASE 2    │ ──> │   PHASE 3    │ ──> │   PHASE 4    │
│  Agent Core  │     │ Core Skills  │     │  Knowledge   │     │ Observation  │
└──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘
                                                                       │
┌──────────────┐     ┌──────────────┐     ┌──────────────┐             │
│   PHASE 8    │ <── │   PHASE 7    │ <── │   PHASE 6    │ <── ────────┘
│ Auto Publish │     │ Platform API │     │  Analytics   │     ┌──────────────┐
└──────────────┘     └──────────────┘     └──────────────┘     │   PHASE 5    │
       │                                                       │   Creative   │
       ▼                                                       │  Production  │
┌──────────────┐     ┌──────────────┐                          └──────────────┘
│   PHASE 9    │ ──> │   PHASE 10   │
│   Learning   │     │  Standalone  │
│  Evaluation  │     │ Application  │
└──────────────┘     └──────────────┘
```

---

### PHASE 1 — Agent Core & Foundational Architecture (CURRENT)
- [x] Initial directory topology and product workspace isolation.
- [x] Architecture specification (`ARCHITECTURE.md`).
- [x] Standard inter-agent communication envelope and epistemic protocol (`AGENT_PROTOCOL.md`).
- [x] Typed domain data schemas in Pydantic / Python (`DATA_MODEL.md` + `schemas/`).
- [x] Least-privilege security model & authorization gate specifications (`SECURITY_MODEL.md`).
- [x] Modular Creative Engine and video editing pipeline specifications (`CREATIVE_ENGINE.md`).
- [x] Dual-track continuous learning and memory model (`LEARNING_SYSTEM.md`).
- [x] Provider-agnostic model router interfaces and foundational unit tests.

---

### PHASE 2 — Core Marketing Skills Framework
- Define high-leverage atomic skills for each specialist agent:
  - **CMO**: Campaign orchestrator, budget allocator, brand compliance checker.
  - **Intelligence**: Competitor ad breakdown, review scraper, persona extractor.
  - **Strategist**: Value-prop matrix generator, hook strategy formulator, offer architect.
  - **Creative**: Hook copywriter, short-form scriptwriter, storyboard compiler.
  - **Performance**: UTM builder, ad variant matrix builder, metrics evaluator.
- Enforce strict typed inputs and structured outputs across all skills.

---

### PHASE 3 — Knowledge & Research Ingestion System
- Populate Tier 1 Global Knowledge Base:
  - Copywriting frameworks (AIDA, PAS, BAB, StoryBrand, Breakthrough Advertising).
  - Consumer psychology principles (Cialdini's influence, loss aversion, status signaling).
  - Platform algorithmic guidelines (TikTok, Reels, YouTube Shorts, Meta Feed).
- Implement semantic vector index and BM25 hybrid search over product documentation and brand files.

---

### PHASE 4 — Social Observation Layer (SOL)
- Build pluggable sensory adapters:
  - **Web Search & Scrape Gateway**: Brave Search / Google Search / Serper.
  - **Social Ad Library Scrapers**: Meta Ad Library, TikTok Creative Center.
  - **Structured Social Connectors**: TikHub / Apify MCP connectors.
  - **Browser Observation Fallback**: Headless Playwright/Puppeteer scraping sandbox.
- Implement epistemic validator enforcing raw citation capture and separation of observations from inferences.

---

### PHASE 5 — Creative Production Engine
- Implement modular generation adapters:
  - Image generation: Midjourney / Flux / SDXL adapters.
  - Video generation: Runway / Kling / Luma adapters.
  - Voice synthesis: ElevenLabs / OpenAI TTS / Local Kokoro / Bark.
  - Headless video assembly: Automated FFmpeg / MoviePy timeline renderer.
- Implement automated caption styling (karaoke subtitle generator) and audio normalization (-14 LUFS).
- Implement QA safe-zone validator for 9:16 vertical video formats.

---

### PHASE 6 — Analytics & Experiment Engine
- Build statistical attribution pipeline linking campaign performance to atomic creative tags.
- Implement automated statistical significance calculator (Bayesian & Frequentist A/B testing).
- Anomaly detection for ad fatigue, CTR decay, and CPC spikes.

---

### PHASE 7 — Platform API Gateway
- Build secure, token-isolated connectors for advertising networks:
  - Meta Marketing API (Campaigns, AdSets, Creatives).
  - TikTok Ads API.
  - Google Ads API.
- Implement two-phase commit transaction manager (`Validate` -> `Hold` -> `Execute`).

---

### PHASE 8 — Controlled Auto-Publishing & Autonomy Engine
- Implement the three-tier Autonomy Engine (`MANUAL`, `SUPERVISED`, `AUTONOMOUS`).
- Build human-in-the-loop approval webhooks (Slack/Discord/Email notifications with one-click sign-off).
- Enforce hard spending caps, automatic budget freeze on CPA anomalies, and rollback triggers.

---

### PHASE 9 — Continuous Learning & Evaluation System
- Implement automated distillation of campaign post-mortems into `Success Memory` and `Failure Memory`.
- Automated decay tracking for marketing insights older than 90 days.
- Knowledge promotion evaluation pipeline with Human/CMO sign-off gates.

---

### PHASE 10 — Standalone Enterprise Application
- Full-stack multi-brand dashboard (FastAPI backend + modern reactive frontend).
- Visual campaign timeline builder, live creative previewer, and experiment visualizer.
- Real-time agent collaboration chat and interactive Ask-Mentor cockpit.
