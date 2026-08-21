# AI Marketing Department Architecture (V1)

## 1. Executive Summary & Purpose

The **AI Marketing Department** is an autonomous, scalable, production-grade multi-agent operating system designed to execute real-world marketing strategy, intelligence, creative production, and performance optimization.

Unlike traditional single-prompt assistants or uncoordinated bot swarms, the AI Marketing Department enforces:
- **Strict Role Specialization**: Five permanent marketing agents with clear boundaries of concern.
- **Hierarchical Orchestration**: The CMO orchestrates work, validates hypotheses, resolves conflicts, and oversees execution.
- **Product & Brand Workspace Isolation**: Multitenant isolation preventing cross-contamination of intelligence, creative assets, and analytics.
- **Provider-Agnostic LLM Routing**: Complete abstraction of model providers (OpenAI, Gemini, Claude, Local/Ollama) via standardized interfaces.
- **Closed-Loop Scientific Method**: Every action begins with a hypothesis, generates measurable variants, tracks performance down to creative components, and extracts empirical learnings.

---

## 2. Five Permanent Agents & Responsibilities

The system consists of **EXACTLY FIVE** permanent AI marketing specialists. Each specialist has defined responsibilities, standard inputs, outputs, and strict boundaries.

```
                   ┌──────────────────────────────────────┐
                   │                 CMO                  │
                   │  Orchestrator & Strategy Governance  │
                   └──────────────────┬───────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
         ▼                            ▼                            ▼
┌──────────────────┐        ┌──────────────────┐        ┌──────────────────┐
│   INTELLIGENCE   │        │    STRATEGIST    │        │     CREATIVE     │
│ Market, Product, │        │ Strategy, Growth │        │ Concept, Copy,   │
│ Consumer & Comp  │        │ & Positioning    │        │ Scripts, Prod    │
└────────┬─────────┘        └────────┬─────────┘        └────────┬─────────┘
         │                           │                           │
         └───────────────────────────┼───────────────────────────┘
                                     │
                                     ▼
                         ┌───────────────────────┐
                         │      PERFORMANCE      │
                         │ Analytics, Operations │
                         │ & Experimentation     │
                         └───────────────────────┘
```

### 2.1 CMO (Chief Marketing Officer / Orchestrator)
- **Role**: Master orchestrator, strategy validator, brand guardian, and resource allocator.
- **Responsibilities**:
  - Receives business objectives and budgets from human leadership.
  - Deconstructs high-level goals into structured tasks using the standard `TaskEnvelope`.
  - Dispatches tasks across the 4 specialist agents and resolves cross-agent conflicts.
  - Reviews and signs off on research reports, marketing strategies, creative storyboards, and campaign plans.
  - Enforces brand integrity, safety guardrails, and compliance policies.
  - Synthesizes post-campaign performance reviews and directs knowledge base updates.
- **Boundaries**: Does not directly generate copy, pull raw API data, or execute ad buys without specialist delegation.

### 2.2 Intelligence (Market, Consumer, Product & Competitor Intelligence)
- **Role**: The investigative and analytical sensory unit.
- **Responsibilities**:
  - Gathers, validates, and synthesizes data across market trends, competitor tactics, and consumer sentiment.
  - Analyzes customer personas, jobs-to-be-done (JTBD), pain points, and desire triggers.
  - Evaluates product features, differentiators, value propositions, and proof points.
  - Produces structured `ResearchReport` entities grounded in verifiable evidence.
- **Boundaries**: Strictly separates `FACT`, `OBSERVATION`, `INFERENCE`, and `HYPOTHESIS`. Never fabricates sources, metrics, or market indicators.

### 2.3 Strategist (Marketing Strategy & Growth)
- **Role**: Positioning architect and tactical growth planner.
- **Responsibilities**:
  - Formulates positioning, messaging hierarchies, and go-to-market (GTM) frameworks.
  - Converts intelligence reports into actionable `MarketingHypothesis` and `MarketingStrategy` blueprints.
  - Designs campaign architectures, channel mixes, customer journeys, and offer mechanics.
  - Defines test parameters, sample sizes, target KPIs, and experiment roadmaps.
- **Boundaries**: Does not execute ad platform setups or produce final creative production assets.

### 2.4 Creative (Creative Director, Copywriter, Scriptwriter & Production Director)
- **Role**: Idea generator, storytelling engine, and multimedia production director.
- **Responsibilities**:
  - Translates strategic briefs into high-converting `CreativeConcept` and `Hook` variations.
  - Writes copy, advertising scripts, headlines, and angles tailored to target personas.
  - Directs visual and audio storytelling via structured `Storyboard` and `Scene` specifications.
  - Coordinates with the Creative Engine for asset generation (image, video, voice, audio, subtitles, editing, rendering).
  - Maintains component-level creative tagging (hook type, angle, editing style, CTA) for granular attribution.
- **Boundaries**: Cannot directly publish content to external channels without Performance/CMO clearance.

### 2.5 Performance (Performance Marketing, Analytics & Marketing Operations)
- **Role**: Experiment executor, media buyer, tracking architect, and quantitative analyst.
- **Responsibilities**:
  - Designs tracking taxonomy (UTMs, event schemas, custom dimensions).
  - Translates strategy into media spend allocation, audience targeting, and bidding configurations.
  - Ingests cross-platform campaign analytics and validates data integrity.
  - Performs statistical attribution linking ROI/conversion data back to specific creative components.
  - Prepares execution orders subject to the active autonomy level (Manual, Supervised, Autonomous).
- **Boundaries**: Strictly governed by security controls and budget caps. Never increases budgets or edits live campaigns beyond authorized thresholds.

---

## 3. Specialist-Agent Cooperation & Orchestration Model

Communication between agents is strictly deterministic and governed by typed protocol envelopes (see `AGENT_PROTOCOL.md`).

```
[Human / CMO Directive]
        │
        ▼
 1. CMO generates TaskEnvelope (Objective, ProductID, Constraints)
        │
        ▼
 2. INTELLIGENCE: Researches market, competitors, customer insights
        │ -> Returns structured ResearchReport + Evidence
        ▼
 3. STRATEGIST: Formulates positioning, campaign angles & test hypotheses
        │ -> Returns MarketingStrategy + ExperimentDesign
        ▼
 4. CREATIVE: Produces concepts, hooks, scripts, storyboards & renders assets
        │ -> Returns CreativeVariants + ComponentMetadata
        ▼
 5. CMO: Reviews strategy & creative package against brand guidelines
        │ -> Signs off or requests iterative revision
        ▼
 6. PERFORMANCE: Prepares campaign structure, tracking parameters & launch payload
        │ -> Executes launch (under configured autonomy mode)
        ▼
 7. PERFORMANCE: Collects ongoing metrics -> Detects statistical anomalies
        │ -> Feeds PerformanceRecord into Learning System
        ▼
 8. SYSTEM: Distills Success/Failure Memory -> Updates Product Knowledge Base
```

---

## 4. Dynamic Subagent Architecture (Future-Ready)

While the system has **EXACTLY FIVE permanent marketing specialists**, the architecture accommodates dynamic, ephemeral subagents spawned for specialized sub-tasks under the supervision of a permanent agent:

- **Intelligence Subagents**: `CompetitorPriceScraper`, `RedditCommunityObserver`, `TrendScanner`, `AmazonReviewMiner`.
- **Creative Subagents**: `ScriptVariationWriter`, `VoiceSynthesisCoordinator`, `SubtitlesAligner`, `ThumbnailVariantGenerator`.
- **Performance Subagents**: `BidAnomalyDetector`, `TrackingTagValidator`, `CreativeFatigueMonitor`.

**Subagent Lifecycle Rules**:
1. Ephemeral: Instantiated with a bounded scope, single `PARENT_TASK_ID`, and destroyed upon completion.
2. Sandboxed: Subagents inherit the exact security boundaries and workspace constraints of their parent agent.
3. Transparent: All subagent reasoning traces and outputs are logged in the parent task audit trail.

---

## 5. Shared Knowledge & Memory Architecture

The memory and knowledge infrastructure operates in three distinct tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        TIER 1: GLOBAL KNOWLEDGE                        │
│ Curated marketing theory, psychology principles, platform algorithms,  │
│ copywriting frameworks (AIDA, PAS, StoryBrand), statistical standards  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│                    TIER 2: WORKSPACE / BRAND MEMORY                    │
│ Brand voice guidelines, core personas, positioning, historical campaigns│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────────┐
│               TIER 3: ISOLATED PRODUCT EXPERIMENT MEMORY               │
│ Hypothesis log, creative component rankings, success memory, failure   │
│ memory, unvalidated observations, statistical learning records         │
└────────────────────────────────────────────────────────────────────────┘
```

### Strict Product Isolation
- Every Product is assigned an immutable `PRODUCT_ID` and dedicated workspace directory: `products/{product_id}/`.
- Data Access Controllers guarantee that Product A's research, creatives, persona data, and analytics can **never** bleed into Product B's context window or vector retrieval query.

---

## 6. Future Integration Layers

### 6.1 Social Observation Layer (SOL)
A pluggable data collection abstraction that feeds the Intelligence agent with real-time market data without vendor lock-in. Adapters will support:
- Web Search & Scrape APIs
- Agent-Reach style connectors
- TikHub / Social data endpoints
- Apify / Crawl MCP servers
- Headless browser observation fallback

### 6.2 Platform Action Layer (PAL)
A secure execution gateway managing outbound interactions (Meta Ads, Google Ads, TikTok Ads, Email/SMS, CMS).
- Enforces OAuth/API secret isolation.
- Implements two-phase commit: `PrepareAction` -> `ValidateRules` -> `CMO/Human Approval` -> `ExecuteAction`.

### 6.3 Model Router & Adapter Architecture
Agents interact with LLMs through a unified provider-agnostic interface:
```
[Agent Core] ──> [ModelRouter] ──> ┬── [OpenAIAdapter]      (GPT-4o, o3-mini)
                                   ├── [GeminiAdapter]      (Gemini 2.0 Flash / Pro)
                                   ├── [AnthropicAdapter]   (Claude 3.5 Sonnet / Opus)
                                   └── [LocalAdapter]       (Ollama / vLLM / DeepSeek)
```
- Routes tasks based on model capability requirements (e.g., fast reasoning, large context window, creative writing, structured JSON extraction).
- Supports automated fallback if a provider experiences rate limiting or downtime.

### 6.4 Ask Mentor System
An advisory subsystem enabling any agent to consult an expert persona (e.g., "Direct Response Copywriting Master", "B2B SaaS Growth Lead", "Brand Compliance Auditor") for second opinions on critical decisions.

### 6.5 Future Standalone Application
The core engine is architected as a headless, API-first backend capable of powering:
- Multi-brand agency dashboards.
- Collaborative Human-in-the-Loop review suites.
- Automated continuous marketing optimization daemons.
