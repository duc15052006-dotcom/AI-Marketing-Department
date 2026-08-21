# AI Marketing Department Data Model (DATA_MODEL.md)

## 1. Overview & Architectural Principles

The data model provides strongly typed entities for the entire marketing lifecycle. Built on Python typing / Pydantic V2 schemas, all entities enforce:
1. **Strict Product & Brand Partitioning**: All child entities (`ResearchReport`, `Campaign`, `ContentAsset`, `Experiment`, `Learning`) require an immutable `product_id` and `brand_id`.
2. **Component-Level Creative Traceability**: Video and ad assets are atomized into `Concept`, `Angle`, `Hook`, `Script`, `Scene`, `EditingStyle`, and `CTA` to enable granular econometric and performance attribution.
3. **Epistemic Traceability**: Every insight, claim, and hypothesis links directly to underlying `Evidence` and `Source` objects.

---

## 2. Core Entity Hierarchy

```
[Brand]
   │
   └── [Product] (Strict Workspace Partition)
          ├── [CustomerPersona] ──> [CustomerInsight] ──> [Evidence] ──> [Source]
          ├── [ResearchReport]
          ├── [MarketingStrategy] ──> [MarketingHypothesis]
          ├── [Campaign]
          │      └── [Experiment]
          │             └── [CreativeVariant] ──> [PerformanceRecord]
          ├── [CreativeConcept]
          │      ├── [Hook]
          │      └── [Script] ──> [Storyboard] ──> [Scene] ──> [VideoAsset]
          └── [Learning / Failure]
```

---

## 3. High-Level Typed Entity Specifications

### 3.1 Workspace & Domain Foundations

#### `Brand`
- `id`: `str` (Format: `BRAND-XXXX`)
- `name`: `str`
- `industry`: `str`
- `mission`: `str`
- `core_values`: `list[str]`
- `voice_guidelines`: `dict[str, Any]` (Tone, vocabulary, forbidden terms)
- `visual_guidelines`: `dict[str, Any]` (Color codes, fonts, aesthetic rules)
- `created_at`: `datetime`
- `updated_at`: `datetime`

#### `Product`
- `id`: `str` (Format: `PROD-XXXX`) - **Immutable Partition Key**
- `brand_id`: `str` (References `Brand.id`)
- `name`: `str`
- `description`: `str`
- `category`: `str`
- `price_model`: `dict[str, Any]` (Price, currency, subscription tier)
- `features`: `list[dict[str, Any]]` (Feature name, benefit, proof point)
- `unique_selling_propositions` (USPs): `list[str]`
- `target_audience_ids`: `list[str]`
- `workspace_path`: `str` (e.g., `products/PROD-001/`)
- `created_at`: `datetime`

---

### 3.2 Intelligence & Research Entities

#### `CustomerPersona`
- `id`: `str` (Format: `PERS-XXXX`)
- `product_id`: `str`
- `name`: `str` (e.g., "Overworked Marketing Director")
- `demographics`: `dict[str, Any]`
- `psychographics`: `dict[str, Any]` (Fears, aspirations, values)
- `jobs_to_be_done` (JTBD): `list[str]`
- `pain_points`: `list[str]`
- `objections`: `list[str]`
- `triggers_to_purchase`: `list[str]`

#### `CustomerInsight`
- `id`: `str` (Format: `INSIGHT-XXXX`)
- `product_id`: `str`
- `persona_id`: `str`
- `statement`: `str`
- `epistemic_type`: `Literal["FACT", "OBSERVATION", "INFERENCE", "HYPOTHESIS"]`
- `evidence_ids`: `list[str]`
- `confidence`: `float`

#### `Evidence` & `Source`
- `Evidence`:
  - `id`: `str` (Format: `EVID-XXXX`)
  - `source_id`: `str`
  - `raw_content`: `str`
  - `timestamp`: `datetime`
  - `verification_status`: `Literal["VERIFIED", "UNVERIFIED", "DISPUTED"]`
- `Source`:
  - `id`: `str` (Format: `SRC-XXXX`)
  - `url`: `Optional[str]`
  - `platform`: `str` (e.g., "Meta Ad Library", "Reddit", "Amazon Reviews")
  - `author_or_entity`: `Optional[str]`
  - `ingested_at`: `datetime`

#### `ResearchReport`
- `id`: `str` (Format: `REP-XXXX`)
- `product_id`: `str`
- `title`: `str`
- `executive_summary`: `str`
- `competitor_analysis`: `list[dict[str, Any]]`
- `market_trends`: `list[str]`
- `identified_insights`: `list[str]` (References `CustomerInsight.id`)
- `recommended_angles`: `list[str]`
- `created_by_agent`: `str` (e.g., "INTELLIGENCE")

---

### 3.3 Strategy & Campaign Planning Entities

#### `MarketingHypothesis`
- `id`: `str` (Format: `HYP-XXXX`)
- `product_id`: `str`
- `statement`: `str` (e.g., *"Highlighting time-saving over cost-saving will increase CTR by 20%"*)
- `rationale`: `str`
- `target_metric`: `str` (e.g., `CTR`, `ROAS`, `ConversionRate`)
- `expected_delta`: `float`
- `status`: `Literal["DRAFT", "ACTIVE_TEST", "VALIDATED", "DISPROVEN"]`

#### `MarketingStrategy`
- `id`: `str` (Format: `STRAT-XXXX`)
- `product_id`: `str`
- `strategic_pillars`: `list[str]`
- `positioning_statement`: `str`
- `value_propositions`: `list[str]`
- `messaging_hierarchy`: `dict[str, Any]`
- `target_channels`: `list[str]`
- `hypothesis_ids`: `list[str]`

#### `Campaign`
- `id`: `str` (Format: `CAMP-XXXX`)
- `product_id`: `str`
- `brand_id`: `str`
- `name`: `str`
- `objective`: `Literal["AWARENESS", "TRAFFIC", "LEAD_GEN", "CONVERSION", "RETENTION"]`
- `strategy_id`: `str`
- `total_budget`: `float`
- `currency`: `str`
- `start_date`: `datetime`
- `end_date`: `Optional[datetime]`
- `status`: `Literal["PLANNING", "IN_REVIEW", "SCHEDULED", "ACTIVE", "PAUSED", "COMPLETED"]`

---

### 3.4 Creative Production Entities

#### `CreativeConcept`
- `id`: `str` (Format: `CONCEPT-XXXX`)
- `product_id`: `str`
- `angle_name`: `str` (e.g., "The Frustrated Professional")
- `theme`: `str`
- `target_persona_id`: `str`
- `emotional_hook_category`: `Literal["FEAR", "CURIOSITY", "STATUS", "RELIEF", "GREED", "ANGER"]`

#### `Hook`
- `id`: `str` (Format: `HOOK-XXXX`)
- `concept_id`: `str`
- `text_hook`: `str`
- `visual_hook_description`: `str`
- `hook_type`: `Literal["QUESTION", "CONTRARIAN", "STORY_IN_MEDIAS_RES", "DIRECT_PAIN", "STATISTIC"]`
- `duration_seconds`: `float` (Usually 1.5 - 3.0s)

#### `Script`
- `id`: `str` (Format: `SCRIPT-XXXX`)
- `concept_id`: `str`
- `hook_id`: `str`
- `target_duration_seconds`: `int`
- `full_text`: `str`
- `call_to_action` (CTA): `str`
- `cta_type`: `Literal["DIRECT_CLICK", "FREE_TRIAL", "DOWNLOAD", "LIMITED_DISCOUNT"]`

#### `Storyboard` & `Scene`
- `Storyboard`:
  - `id`: `str` (Format: `SB-XXXX`)
  - `script_id`: `str`
  - `scene_sequence`: `list[str]` (Ordered list of `Scene.id`)
  - `aspect_ratio`: `Literal["9:16", "16:9", "1:1", "4:5"]`
- `Scene`:
  - `id`: `str` (Format: `SCN-XXXX`)
  - `sequence_index`: `int`
  - `duration_seconds`: `float`
  - `visual_description`: `str`
  - `voiceover_text`: `str`
  - `on_screen_text` (OST): `str`
  - `audio_sfx_cue`: `Optional[str]`
  - `camera_movement`: `str` (e.g., "Zoom-in", "Pan left", "Static close-up")

#### `ContentAsset` & `VideoAsset`
- `ContentAsset`:
  - `id`: `str` (Format: `ASSET-XXXX`)
  - `product_id`: `str`
  - `asset_type`: `Literal["IMAGE", "VIDEO", "AUDIO", "VOICEOVER", "SUBTITLE", "THUMBNAIL"]`
  - `file_path`: `str`
  - `resolution`: `str`
  - `mime_type`: `str`
  - `generation_params`: `dict[str, Any]` (Model used, seed, prompt)
- `VideoAsset`:
  - Inherits from `ContentAsset`
  - `storyboard_id`: `str`
  - `script_id`: `str`
  - `hook_id`: `str`
  - `duration_seconds`: `float`
  - `timeline_manifest_path`: `str`

---

### 3.5 Experimentation & Analytics Entities

#### `Experiment`
- `id`: `str` (Format: `EXP-XXXX`)
- `campaign_id`: `str`
- `product_id`: `str`
- `hypothesis_id`: `str`
- `experiment_type`: `Literal["A_B_TEST", "MULTIVARIATE", "BANDIT"]`
- `control_variant_id`: `str`
- `test_variant_ids`: `list[str]`
- `sample_size_target`: `int`
- `confidence_level`: `float` (e.g., 0.95)
- `status`: `Literal["DRAFT", "RUNNING", "CONCLUDED", "INCONCLUSIVE"]`

#### `CreativeVariant`
- `id`: `str` (Format: `VAR-XXXX`)
- `experiment_id`: `str`
- `video_asset_id`: `str`
- `hook_id`: `str`
- `script_id`: `str`
- `cta_id`: `str`
- `editing_style`: `str`
- `platform_placement_id`: `Optional[str]`

#### `PerformanceRecord`
- `id`: `str` (Format: `PERF-XXXX`)
- `product_id`: `str`
- `variant_id`: `str`
- `channel`: `str` (e.g., "Meta", "TikTok", "YouTube")
- `date`: `date`
- `impressions`: `int`
- `spend`: `float`
- `clicks`: `int`
- `video_views_3s`: `int`
- `video_views_100pct`: `int`
- `conversions`: `int`
- `revenue`: `float`
- `ctr`: `float`
- `cpc`: `float`
- `cpa`: `float`
- `roas`: `float`

---

### 3.6 Memory, Learning & Task Entities

#### `Learning`
- `id`: `str` (Format: `LRN-XXXX`)
- `product_id`: `str`
- `hypothesis_id`: `Optional[str]`
- `observation`: `str`
- `evidence`: `list[str]`
- `sample_size`: `int`
- `context`: `dict[str, Any]`
- `result`: `str`
- `confidence`: `float`
- `scope`: `Literal["PRODUCT_SPECIFIC", "BRAND_WIDE", "GLOBAL_MARKETING"]`
- `possible_confounders`: `list[str]`
- `recommendation`: `str`
- `needs_retest`: `bool`

#### `Failure`
- `id`: `str` (Format: `FAIL-XXXX`)
- `product_id`: `str`
- `experiment_id`: `Optional[str]`
- `description`: `str`
- `root_cause_analysis`: `str`
- `preventative_rule`: `str`

#### `AgentTask` & `AgentResult`
- `AgentTask`: Implements `TaskEnvelope` (from `AGENT_PROTOCOL.md`)
- `AgentResult`:
  - `task_id`: `str`
  - `owner_agent`: `str`
  - `status`: `Literal["SUCCESS", "FAILED", "ESCALATED"]`
  - `payload`: `dict[str, Any]` (Validated against expected schema)
  - `epistemic_breakdown`: `dict[str, list[str]]` (Facts, Observations, Inferences, Hypotheses)
  - `confidence`: `float`
  - `execution_duration_seconds`: `float`
