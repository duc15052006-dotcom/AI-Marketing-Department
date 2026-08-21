# Continuous Learning & Memory System (LEARNING_SYSTEM.md)

## 1. Philosophical Grounding & Scientific Method

Marketing is not static intuition; it is an empirical, evolving science. In the AI Marketing Department, **no insight is treated as permanent dogma**, and no agent is permitted to hallucinate unproven "best practices."

The Learning System operates on a strict empirical loop:

```
     ┌────────────────────────────────────────────────────────┐
     │                      1. OBSERVE                        │
     │   (Social trends, audience sentiment, competitor moves)│
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                      2. RESEARCH                       │
     │      (Deep dive into persona pain points & data)       │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                     3. HYPOTHESIS                      │
     │     (Falsifiable prediction with target metrics)       │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                       4. CREATE                        │
     │       (Creative variants with tagged components)       │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                        5. TEST                         │
     │         (Controlled A/B or multivariate spend)         │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                       6. MEASURE                       │
     │           (Collect granular impression/ad data)        │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                       7. ANALYZE                       │
     │     (Component attribution, statistical confidence)    │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                        8. LEARN                        │
     │    (Distill into Success Memory or Failure Memory)     │
     └───────────────────────────┬────────────────────────────┘
                                 ▼
     ┌────────────────────────────────────────────────────────┐
     │                       9. RETEST                        │
     │      (Re-evaluate over time to detect ad fatigue)      │
     └────────────────────────────────────────────────────────┘
```

---

## 2. Dual-Track Memory Architecture

The system treats failures with the exact same rigor as successes.

```
                                  [Experiment Analyzed]
                                            │
                     ┌──────────────────────┴──────────────────────┐
                     ▼                                             ▼
          ┌─────────────────────┐                       ┌─────────────────────┐
          │   SUCCESS MEMORY    │                       │   FAILURE MEMORY    │
          ├─────────────────────┤                       ├─────────────────────┤
          │ Validated patterns  │                       │ Disproven hypotheses│
          │ High-converting hooks│                       │ Costly mistakes     │
          │ Scalable angles     │                       │ Creative fatigue    │
          │ Positive ROAS rules │                       │ Ineffective angles  │
          └──────────┬──────────┘                       └──────────┬──────────┘
                     │                                             │
                     └──────────────────────┬──────────────────────┘
                                            ▼
                              [EVALUATION & PROMOTION GATE]
                                            │
                                            ▼
                              [TIER 1 & 2 KNOWLEDGE BASE]
```

### 2.1 Success Memory (`memory/learnings/`)
Captures statistically significant positive outcomes, detailing what worked, under what precise context, and with what confidence.

### 2.2 Failure Memory (`memory/failures/`)
Preserves negative results to prevent the AI Marketing Department from repeating costly errors. When a strategist or creative drafts a new campaign, the system automatically checks proposed angles against Failure Memory.

---

## 3. The Typed Learning Record Schema

Every distilled learning must conform to the following schema:

```json
{
  "learning_id": "LRN-20260816-089",
  "product_id": "PROD-CRM-01",
  "brand_id": "BRAND-NEXUS",
  "hypothesis_id": "HYP-20260810-014",
  "experiment_id": "EXP-20260812-003",

  "observation": "Video variants starting with an unexpected spreadsheet error visual generated 42% higher 3s retention than standard talking-head intros.",
  "evidence": [
    "Ad Variant VAR-012: 3s View Rate = 48.2% (N=14,200 impressions)",
    "Ad Variant VAR-013 (Control): 3s View Rate = 33.9% (N=14,500 impressions)",
    "P-value = 0.0018 (Statistically Significant at 99% confidence)"
  ],
  "sample_size": 28700,
  "context": {
    "platform": "TikTok Ads & Instagram Reels",
    "target_audience": "US B2B Founders & Ops Managers",
    "campaign_objective": "Lead Generation",
    "ad_spend_usd": 1250.00
  },
  "result": "HYPOTHESIS_CONFIRMED",
  "confidence": 0.96,
  "scope": "PRODUCT_SPECIFIC",
  "possible_confounders": [
    "Competitor campaign paused during the test window",
    "Weekend impression dynamics"
  ],
  "recommendation": "Adopt 'visual software glitch' as the standard primary hook for Top-of-Funnel video ad batches in Q3.",
  "needs_retest": true,
  "retest_scheduled_date": "2026-09-15"
}
```

---

## 4. Knowledge Promotion & Evaluation Lifecycle

A single successful experiment **does not** immediately become permanent global truth. The system enforces a three-stage promotion pipeline:

```
[Experiment Result]
       │
       ▼
 [STATIONARY LEARNING] (Scope: Single Product Experiment)
       │
       │ (Repeated validation across 3+ independent experiments)
       ▼
 [PROMOTED PRODUCT MEMORY] (Scope: Permanent Product Workspace Rule)
       │
       │ (Cross-product / Cross-brand verification + CMO & Human Review)
       ▼
 [GLOBAL KNOWLEDGE BASE] (Scope: Global Marketing Knowledge in `knowledge/`)
```

### Promotion Criteria for Global Knowledge:
1. **Multi-Cohort Validation**: Effect observed across multiple audience segments or campaigns.
2. **Confounder Elimination**: Confounders explicitly analyzed and ruled out.
3. **Decay & Retesting**: Learnings older than 90 days without retesting are flagged as `DECAY_WARNING` to prevent stale algorithm assumptions from biasing new campaigns.
