# Platform Batch 3 — Memory Manager v1

Branch: `platform/memory-manager-v1`

## Existing foundation

The repository already had six memory types, a promotion engine, operator services, learning operations, and a simple local repository. Batch 3 adds the governed storage/retrieval layer around those primitives rather than replacing agent logic.

## Gaps addressed

- Legacy local repository returned mutable object references.
- Memory queries had no repository-enforced scope parameter.
- Retired/disproven/expired memories could still be returned by ordinary query paths.
- Expired working memory was hard-deleted, losing audit history.
- A caller could construct a new memory directly as VERIFIED or PROMOTED.
- The lower-level promotion engine could be called in a way that skipped the intended RAW -> CANDIDATE -> VERIFIED -> PROMOTED sequence.
- No manager-level supersession guard prevented cross-scope replacement.
- No default per-memory-type retention policy existed as one managed contract.

## Added

### `memory/lifecycle_models.py`

- Exact `MemoryScope` for business/project/brand/product/campaign isolation.
- Lifecycle states: ACTIVE, ARCHIVED, DISPROVEN, RETIRED, SUPERSEDED, EXPIRED.
- Per-type retention policies.
- Defaults:
  - WORKING: 1 day
  - EPISODIC: 365 days
  - DECISION: 365 days
  - EXPERIMENT: 730 days
  - SUCCESS/FAILURE: 730 days
  - USER/BRAND PREFERENCE: no automatic expiry

The defaults are policy values, not claims of universal best practice, and can be overridden at construction time.

### `memory/scoped_repository.py`

- Defensive-copy save/get/list/query behavior.
- Exact scope filters.
- Normal retrieval excludes inactive, retired, and past-expiry memories.
- Confidence and promotion-level filters.
- Working-memory expiry is audit-safe: items are marked EXPIRED rather than deleted.

### `memory/manager.py`

- Governed `remember` entrypoint.
- Blocks new memory from entering directly as VERIFIED or PROMOTED.
- Scope-local content/context deduplication.
- Exact scope retrieval with optional GLOBAL fallback.
- Strict promotion sequence:
  RAW_OBSERVATION -> CANDIDATE_MEMORY -> VERIFIED_MEMORY -> PROMOTED_LEARNING.
- Reuses the existing `MemoryPromotionEngine` for evidence, confidence, and review-rationale checks.
- Retire and disprove lifecycle operations.
- Same-scope supersession only.
- Retention expiry processing.
- Lifecycle event records for creation, promotion, retirement, disproval, supersession, and expiry.

## Deliberately not wired into core yet

This batch does not modify agent prompts, CMO orchestration, model routing, existing memory call sites, or the five permanent agent definitions. Runtime integration should occur only after the core hardening stream stabilizes.

## Regression coverage

`tests/test_platform_memory_manager_v1.py` covers:

- scope isolation + global fallback;
- verified/promoted creation bypass prevention;
- sequential promotion and evidence requirements;
- audit-safe working-memory expiry;
- retired/disproven/superseded retrieval exclusion;
- cross-scope supersession denial;
- defensive copies;
- scope-local deduplication.
