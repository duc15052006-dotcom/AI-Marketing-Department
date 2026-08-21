# Grounding Context Specification (GROUNDING_CONTEXT_SPEC.md)

## 1. Purpose & Contract
`GroundingContext` is the model-facing contract delivered to the `Intelligence` agent during market research, JTBD discovery, competitor analysis, and evidence gathering. It transforms an `EvidenceBundle` into an explicit, constraint-driven structure that eliminates hallucination risks and enforces strict evidential grounding.

---

## 2. Structure & Fields

```json
{
  "context_id": "GCTX-ABCD1234",
  "task": "Analyze consumer sentiment for desk lamps",
  "business_context": "Desk lamp product line launch research",
  "product_id": "PROD_DESK_LAMP",
  "brand_id": "BRAND_LUMEN",
  "known_facts": [
    "Empirical evidence bundle 'BNDL-12345678' assembled for research question."
  ],
  "unknown_facts": [
    "Missing TRANSACTION_DATA: Are customer complaints impacting unit returns?"
  ],
  "evidence_bundle_reference": "BNDL-12345678",
  "evidence_items": [
    {
      "evidence_id": "EVID-WEB-001",
      "capability": "read_page",
      "content_role": "PRIMARY_CONTENT",
      "source_platform": "web",
      "source_domain": "example.com",
      "source_provenance": "FIRST_PARTY_WEBSITE",
      "evidence_class": "OBSERVATION",
      "content_trust": "UNTRUSTED_EXTERNAL",
      "source_credibility": "UNKNOWN",
      "content_truth_status": "UNVERIFIED",
      "freshness_state": "CURRENT",
      "freshness_days": 2.5,
      "bounded_content": "Full extracted article text...",
      "content_truncated": false,
      "duplicate_of": null,
      "limitations": []
    }
  ],
  "conflicts": [],
  "evidence_gaps": [],
  "sampling_notes": [
    "Total evidence items: 5 across 3 domains and 2 platforms."
  ],
  "freshness_notes": [
    "Freshness breakdown: {'CURRENT': 4, 'RECENT': 1}"
  ],
  "source_limitations": [
    "Search snippets represent discovery pointers and are segregated from substantive fetched page evidence."
  ],
  "grounding_rules": [
    "Use supplied evidence items strictly for assertions represented as evidence-supported.",
    "Cite Evidence IDs (e.g. 'EVID-...') for all empirical claims and findings.",
    "Search snippets are discovery pointers; substantive claims require fetched page evidence.",
    "Platform-reported metrics (views, likes, comments) are external observations, not verified sales or demand.",
    "User-generated content (reviews, forum posts) reflects pseudonymous opinions, not verified objective truth.",
    "Preserve UNKNOWN status when evidence is absent; do not hallucinate missing variables.",
    "Preserve unresolved conflicts rather than silently inventing resolutions.",
    "Distinguish FACT / OBSERVATION / INFERENCE / HYPOTHESIS strictly in reasoning output."
  ]
}
```

---

## 3. Grounding Rules & Model Constraints
1. **Mandatory Citations**: Any claim represented as empirically supported must explicitly cite its `evidence_id` (e.g. `[EVID-WEB-001]`).
2. **Discovery Segregation**: Search snippets may never be cited as verified full-page assertions.
3. **No Metric Upgrades**: Platform metrics (views, likes) may never be inferred as verified customer sales, transaction volume, or brand revenue.
4. **Preserve Unknowns**: If an evidence gap exists, the reasoning must state `UNKNOWN` and preserve the gap.
