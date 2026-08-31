# Platform Batch 2 — Knowledge / File Manager v1

Branch: `platform/knowledge-file-manager-v1`

## Why this batch exists

The repository already had useful Phase 5/6 knowledge primitives (`knowledge/models.py`, `knowledge/repository.py`, `knowledge/ingestion.py`, `knowledge/conflicts.py`). Batch 2 extends those foundations instead of replacing them or modifying the five-agent core.

The existing code also exposed several production gaps:

- local parsing could read an arbitrary existing `Path` without routing through the repository's hardened filesystem containment primitive;
- legacy local repository versions stored hashes but not immutable full-document snapshots;
- normal retrieval did not have a managed active/inactive lifecycle boundary;
- `min_authority` existed in the legacy query contract but was not enforced by the legacy implementation;
- scope was a free-form string and had no canonical workspace isolation contract;
- replacement/supersession, audit-safe deletion, and version restore were not available as one governed manager;
- URL ingestion could create placeholder text without real extracted source content.

## Added

### `knowledge/lifecycle_models.py`

- `KnowledgeScope` with canonical exact-scope keys for business/project/brand/product/campaign.
- `KnowledgeLifecycleState`: ACTIVE, STALE, SUPERSEDED, RETIRED, DELETED.
- `KnowledgeIndexState`.
- `KnowledgeFileAsset` with relative-path-only provenance.
- `KnowledgeImportResult`.

### `knowledge/versioned_repository.py`

- Defensive-copy storage: caller mutation cannot mutate repository truth.
- Full immutable `KnowledgeDocument` snapshot for every saved version.
- Version lookup and restore.
- Enforced minimum authority floor.
- Retired/superseded/deleted documents excluded from normal list/query operations.
- Lifecycle transitions are themselves versioned.
- Supersession links (`superseded_by_id`, `supersedes_id`).
- Soft delete only; no public hard-delete path.
- Provenance verification checks document, source, optional chunk, and current content hash.

### `knowledge/file_manager.py`

- Governed local-file ingestion through the existing `tools.filesystem_guard.resolve_safe_path` primitive.
- No absolute paths or traversal outside the configured workspace root.
- Allowed v1 formats: UTF-8 TXT, Markdown, JSON, CSV.
- File-size limit and controlled parsing.
- Relative path provenance; absolute host paths are not stored in file-asset records.
- Exact scope retrieval with optional GLOBAL knowledge fallback.
- Content-hash deduplication within a scope.
- Manual text ingestion.
- Observed-URL ingestion requires actual extracted content; the manager does not pretend it fetched a URL.
- Replace -> new document + supersede old document.
- Retire, audit-safe soft delete, restore version.

## Isolation rule

For a request scoped to `PROJECT:A`, retrieval can return:

1. exact `PROJECT:A` documents; and
2. `GLOBAL` documents only when `include_global=True`.

It does not return `PROJECT:B`, another product, brand, or campaign scope.

## Deliberately not wired into core yet

This batch does not change:

- five permanent agent definitions;
- CMO orchestration;
- model/provider routing;
- existing agent prompt composition;
- existing `KnowledgeLifecycleManager` call sites.

A later integration batch can switch selected runtime consumers to `KnowledgeFileManager` after core hardening stabilizes.

## Regression coverage

`tests/test_platform_knowledge_file_manager_v1.py` covers:

- sandboxed file ingestion;
- path traversal and absolute path blocking;
- exact scope isolation + global fallback;
- inactive document retrieval exclusion;
- authority floors;
- immutable and restorable version snapshots;
- replacement/supersession;
- real-content requirement for observed URLs;
- source/chunk/hash provenance;
- defensive-copy repository behavior.
