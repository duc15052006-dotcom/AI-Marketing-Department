"""Verifier model snapshot integrity (PROD-VERIFIER-02D). Torch-free.

Manifest schema (VERIFIER_MODEL_MANIFEST_V1):
{
  "manifest_version": 1,
  "model_id": "<repo id>",
  "model_revision": "<full 40-hex commit>",
  "files": [
    {"path": "config.json", "sha256": "<64-hex>", "size": 123},
    ...
  ]
}

Trust rules:
- A manifest is TRUSTED only when provisioned by an explicit out-of-band
  attestation/provisioning step. Building one from whatever files happen to
  sit in a local cache at runtime and then trusting it is TOFU and is
  forbidden here.
- Strict mode (default): neural load is refused when no trusted manifest is
  available for the pinned model/revision (MODEL_INTEGRITY_MANIFEST_MISSING).
- Manifest paths must stay inside the authorized cache/snapshot root:
  absolute paths, '..' components, drive/root escapes, and symlink/junction
  targets escaping the authorized tree are rejected. Legitimate HF-style
  internal blob indirection is allowed as long as the RESOLVED target stays
  inside the authorized tree.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_VERSION = 1

# Stable integrity error categories
E_MANIFEST_MISSING = "MODEL_INTEGRITY_MANIFEST_MISSING"
E_MANIFEST_INVALID = "MODEL_INTEGRITY_MANIFEST_INVALID"
E_TAMPERED = "MODEL_ASSETS_TAMPERED"
E_PATH_ESCAPE = "INTEGRITY_PATH_ESCAPE"
E_IDENTITY_MISMATCH = "MODEL_IDENTITY_MISMATCH"


class IntegrityFailure(Exception):
    def __init__(self, category: str, message: str = "") -> None:
        super().__init__(message or category)
        self.category = category


def _is_full_commit(revision: str) -> bool:
    r = str(revision or "")
    return len(r) == 40 and all(c in "0123456789abcdef" for c in r)


def load_manifest(manifest_path: Path) -> Dict[str, Any]:
    """Load + schema-validate a trusted manifest file."""
    if not manifest_path.is_file():
        raise IntegrityFailure(E_MANIFEST_MISSING,
                               f"trusted manifest not found: {manifest_path.name}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise IntegrityFailure(E_MANIFEST_INVALID, f"manifest JSON unreadable: {e}") from e
    validate_manifest_schema(manifest)
    return manifest


def validate_manifest_schema(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise IntegrityFailure(E_MANIFEST_INVALID, "manifest must be an object")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise IntegrityFailure(E_MANIFEST_INVALID, "unsupported manifest_version")
    if not isinstance(manifest.get("model_id"), str) or not manifest["model_id"]:
        raise IntegrityFailure(E_MANIFEST_INVALID, "model_id missing")
    if not _is_full_commit(manifest.get("model_revision", "")):
        raise IntegrityFailure(E_MANIFEST_INVALID,
                               "model_revision must be a full 40-char commit hash")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise IntegrityFailure(E_MANIFEST_INVALID, "files list missing/empty")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict):
            raise IntegrityFailure(E_MANIFEST_INVALID, "file entry must be object")
        p = entry.get("path")
        h = entry.get("sha256")
        if not isinstance(p, str) or not p:
            raise IntegrityFailure(E_MANIFEST_INVALID, "file path missing")
        if not isinstance(h, str) or len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
            raise IntegrityFailure(E_MANIFEST_INVALID, f"invalid sha256 for {p}")
        size = entry.get("size")
        if not isinstance(size, int) or size < 0:
            raise IntegrityFailure(E_MANIFEST_INVALID, f"invalid size for {p}")
        norm = p.replace("\\", "/").lower()
        if norm in seen:
            raise IntegrityFailure(E_MANIFEST_INVALID, f"duplicate file entry {p}")
        seen.add(norm)


def _resolved_within(path: Path, root: Path) -> bool:
    """True when resolved path stays inside resolved root (same drive on Windows)."""
    try:
        rp = os.path.realpath(str(path))
        rr = os.path.realpath(str(root))
        pr = Path(rp).resolve()
        rrn = Path(rr).resolve()
        if pr.drive != rrn.drive:
            return False
        return str(pr).lower().startswith(str(rrn).lower() + os.sep)
    except Exception:
        return False


def check_path_containment(relative_path: str, snapshot_dir: Path, cache_root: Path) -> Path:
    """Reject absolute paths, '..' escapes and symlink/junction escape before
    any file read. Returns the resolved real path that will be hashed."""
    if os.path.isabs(relative_path) or relative_path.startswith("\\\\"):
        raise IntegrityFailure(E_PATH_ESCAPE, f"absolute manifest path rejected: {relative_path}")
    rel = Path(relative_path.replace("\\", "/"))
    if any(part == ".." for part in rel.parts):
        raise IntegrityFailure(E_PATH_ESCAPE, f"'..' rejected: {relative_path}")
    joined = snapshot_dir / rel
    # Reject symlink/junction components inside the snapshot itself unless the
    # REALPATH target still lives under the authorized cache root (allows
    # legitimate HF blobs/ indirection while blocking tree escapes).
    probe = snapshot_dir
    for part in rel.parts[:-1]:
        probe = probe / part
        if probe.is_symlink() or (os.name == "nt" and probe.exists() and (
                bool(os.lstat(probe).st_file_attributes & 0x400) if hasattr(os, "lstat") else False)):
            pass  # intermediate link: containment decided on final realpath
    final_resolved = Path(os.path.realpath(str(joined)))
    authorized_tree = Path(os.path.realpath(str(cache_root)))
    if not _resolved_within(final_resolved, authorized_tree):
        raise IntegrityFailure(E_PATH_ESCAPE,
                               f"resolved path escapes authorized cache tree: {relative_path}")
    return final_resolved


def sha256_file(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def verify_snapshot_against_manifest(
    manifest: Dict[str, Any],
    snapshot_dir: Path,
    cache_root: Path,
    expected_model_id: str,
    expected_model_revision: str,
) -> List[str]:
    """Validate identity + every required file's size/hash BEFORE model load.
    Returns the verified relative file paths on success; raises IntegrityFailure."""
    if manifest.get("model_id") != expected_model_id:
        raise IntegrityFailure(E_IDENTITY_MISMATCH,
                               f"manifest model_id '{manifest.get('model_id')}' != expected '{expected_model_id}'")
    if manifest.get("model_revision") != expected_model_revision:
        raise IntegrityFailure(E_IDENTITY_MISMATCH,
                               f"manifest revision mismatch (expected pinned commit)")
    if not snapshot_dir.is_dir():
        raise IntegrityFailure(E_MANIFEST_MISSING, "snapshot directory does not exist")

    verified: List[str] = []
    for entry in manifest["files"]:
        real_path = check_path_containment(entry["path"], snapshot_dir, cache_root)
        if not real_path.is_file():
            raise IntegrityFailure(E_TAMPERED, f"required file missing: {entry['path']}")
        actual_hash, actual_size = sha256_file(real_path)
        if actual_hash != entry["sha256"] or actual_size != entry["size"]:
            raise IntegrityFailure(E_TAMPERED, f"hash/size mismatch for {entry['path']}")
        verified.append(entry["path"])
    return verified
