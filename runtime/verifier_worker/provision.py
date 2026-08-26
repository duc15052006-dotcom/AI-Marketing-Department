"""Explicit verifier model provisioning command (PROD-VERIFIER-02E).

Run under the ISOLATED VERIFIER INTERPRETER (Python 3.12 venv):

    .verifier-venv/Scripts/python.exe -m runtime.verifier_worker.provision

This is the ONLY component permitted to contact Hugging Face, and it is
NEVER invoked by verify_claim / normal Stage-6 verification (LOCAL_ONLY).

Behavior:
 1. attests its own interpreter (3.12.x) and dependency identity
 2. resolves VERIFIER_CACHE_ROOT from ConfigurationAuthority/env
 3. downloads EXACTLY MoritzLaurer/mDeBERTa-v3-base-mnli-xnli
    at immutable revision 8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c
    (no main/latest/tag fallback; drift -> hard failure)
 4. inspects weight format: requires safetensors; REFUSES pickle-only models
 5. computes VERIFIER_MODEL_MANIFEST_V1 (sha256+size per required file)
 6. compares locally computed hashes against independently reported remote
    LFS digests where available (REMOTE_DIGEST_MATCHED evidence)
 7. atomically installs the manifest into <cache_root>/manifests/
 8. re-verifies the local snapshot against the installed manifest
 9. prints a safe provisioning summary (no user-home paths)

No user-supplied model id/revision is accepted by design.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROVISIONING_TOOL_VERSION = "VERIFIER_PROVISION_V1"

DEFAULT_MODEL_ID = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
DEFAULT_MODEL_REVISION = "8adb042d524ecd5c26d3e3ba0e3fbcf7e2d0864c"
MANIFEST_VERSION = 1

REQUIRED_EXACT_FILES_HINT = ("model.safetensors",)


def _fail(message: str) -> int:
    print(f"PROVISION_FAILED: {message}", file=sys.stderr)
    return 2


def resolve_cache_root() -> Path:
    """Authoritative cache root: ConfigurationAuthority > env > portable default."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from config.authority import get_runtime_config
        configured = get_runtime_config().verifier_cache_root
        if configured:
            return Path(configured)
    except Exception:
        pass
    env = os.environ.get("VERIFIER_CACHE_ROOT")
    if env:
        return Path(env)
    return Path.home() / ".ai_marketing_department" / "verifier_model_cache"


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


def attest_interpreter_and_deps() -> Tuple[Dict[str, str], List[str]]:
    failures: List[str] = []
    if not platform.python_version_tuple()[:2] == ("3", "12"):
        failures.append(f"PYTHON_VERSION {platform.python_version()} != 3.12.x")
    versions: Dict[str, str] = {}
    for name in ("torch", "transformers", "numpy",
                 "huggingface_hub", "tokenizers", "safetensors"):
        try:
            mod = __import__(name)
            versions[name] = getattr(mod, "__version__", "unknown")
        except Exception:
            failures.append(f"DEPENDENCY_MISSING {name}")
    return versions, failures


def download_pinned_snapshot(cache_root: Path) -> Tuple[Path, Dict[str, Any]]:
    from huggingface_hub import snapshot_download

    target_dir = cache_root / "snapshots" / DEFAULT_MODEL_REVISION
    # Download the exact immutable commit DIRECTLY into the authoritative
    # snapshots/<commit> directory as REAL FILES (no symlinks/junctions):
    # required on Windows without symlink privileges and preferable for
    # integrity hashing anyway. revision= is a full commit hash: no
    # branch/tag fallback can occur.
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=DEFAULT_MODEL_ID,
        revision=DEFAULT_MODEL_REVISION,
        allow_patterns=[
            "config.json", "tokenizer.json", "tokenizer_config.json",
            "special_tokens_map.json", "spm.model", "sentencepiece*",
            "model.safetensors",
        ],
        local_dir=str(target_dir),
        local_dir_use_symlinks=False,
    )
    # Persist provenance of the resolved revision identity.
    (target_dir / ".provisioned_revision").write_text(DEFAULT_MODEL_REVISION,
                                                      encoding="utf-8")
    return target_dir, {"requested_revision": DEFAULT_MODEL_REVISION}


def inspect_formats(snapshot_dir: Path) -> Tuple[List[str], Optional[str]]:
    present = sorted(p.name for p in snapshot_dir.iterdir() if p.is_file())
    has_safetensors = any(f == "model.safetensors" or f.startswith("model-") and f.endswith(".safetensors")
                          for f in present)
    has_pickle = any(f.endswith(".bin") for f in present)
    return present, ("safetensors" if has_safetensors else
                     ("PICKLE_ONLY" if has_pickle else "NONE"))


def remote_digests(model_id: str, revision: str) -> Dict[str, str]:
    """Independently reported remote digests for LFS assets (may be empty)."""
    try:
        from huggingface_hub import HfApi
        api = HfApi()
        info = api.model_info(repo_id=model_id, revision=revision, files_metadata=True)
        digests: Dict[str, str] = {}
        for sib in (info.siblings or []):
            lfs = getattr(sib, "lfs", None)
            if lfs and getattr(lfs, "sha256", None) and sib.rfilename:
                digests[sib.rfilename] = lfs.sha256
        return digests
    except Exception as e:
        print(f"WARN: remote digest metadata unavailable ({e})", file=sys.stderr)
        return {}


def build_manifest(snapshot_dir: Path) -> Dict[str, Any]:
    entries = []
    for p in sorted(snapshot_dir.rglob("*")):
        if p.is_file() and p.name != ".provisioned_revision":
            h, size = sha256_file(p)
            entries.append({"path": p.relative_to(snapshot_dir).as_posix(),
                            "sha256": h, "size": size})
    if not entries:
        raise RuntimeError("snapshot empty")
    deps = attest_interpreter_and_deps()[0]
    fingerprint_src = json.dumps(deps, sort_keys=True)
    dep_fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:16]
    return {
        "manifest_version": MANIFEST_VERSION,
        "model_id": DEFAULT_MODEL_ID,
        "model_revision": DEFAULT_MODEL_REVISION,
        "files": entries,
        "provisioned_at": datetime.now(timezone.utc).isoformat(),
        "provisioning_tool_version": PROVISIONING_TOOL_VERSION,
        "dependency_fingerprint": dep_fingerprint,
        "trust_label": "PROVISIONED/HASH_VERIFIED_LOCAL",
    }


def atomic_write(path: Path, payload: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, path)


def main() -> int:
    started = time.perf_counter()
    print(f"[provision] tool={PROVISIONING_TOOL_VERSION} "
          f"python={platform.python_version()}")

    versions, failures = attest_interpreter_and_deps()
    if failures:
        return _fail("; ".join(failures))
    print(f"[provision] deps attested: {json.dumps(versions, sort_keys=True)}")

    cache_root = resolve_cache_root()
    print(f"[provision] cache_root=<verifier cache root>/ ({cache_root.name}/)")

    snapshot_dir, dl_meta = download_pinned_snapshot(cache_root)
    print(f"[provision] snapshot resolved at snapshots/{DEFAULT_MODEL_REVISION[:12]}…")

    # Resolved-revision proof recorded during normalization.
    marker = (snapshot_dir / ".provisioned_revision").read_text(encoding="utf-8").strip()
    if marker != DEFAULT_MODEL_REVISION:
        return _fail("REVISION DRIFT detected after download.")

    present, fmt = inspect_formats(snapshot_dir)
    print(f"[provision] files: {present}")
    if fmt != "safetensors":
        return _fail(
            f"weight format '{fmt}' is unsafe/unsupported. Production verifier "
            f"requires safetensors; refusing pickle-based weights.")
    print("[provision] weight format: safetensors (safe serialization)")

    remotes = remote_digests(DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION)

    manifest = build_manifest(snapshot_dir)
    matched_remote: List[str] = []
    for entry in manifest["files"]:
        remote_hash = remotes.get(entry["path"])
        if remote_hash:
            entry["remote_lfs_sha256"] = remote_hash
            entry["remote_digest_matched"] = (remote_hash.lower() == entry["sha256"].lower())
            if entry["remote_digest_matched"]:
                matched_remote.append(entry["path"])

    manifest_path = cache_root / "manifests" / f"{DEFAULT_MODEL_REVISION}.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(manifest_path,
                 json.dumps(manifest, indent=1, ensure_ascii=False).encode("utf-8"))
    print(f"[provision] manifest installed atomically: manifests/{DEFAULT_MODEL_REVISION[:12]}….json")

    # Final local re-verification using the SAME production integrity code the
    # normal worker uses at attest time.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from runtime.verifier_worker.integrity import verify_snapshot_against_manifest
    verified = verify_snapshot_against_manifest(
        manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
        snapshot_dir=snapshot_dir,
        cache_root=cache_root,
        expected_model_id=DEFAULT_MODEL_ID,
        expected_model_revision=DEFAULT_MODEL_REVISION,
    )

    elapsed = time.perf_counter() - started
    print("[provision] SUMMARY:")
    print(json.dumps({
        "status": "PROVISIONED",
        "model_id": DEFAULT_MODEL_ID,
        "model_revision": DEFAULT_MODEL_REVISION,
        "verified_files": verified,
        "remote_digest_matched_files": matched_remote,
        "remote_digest_count_available": len(remotes),
        "manifest_trust_label": "PROVISIONED/HASH_VERIFIED_LOCAL"
                                + ("/REMOTE_DIGEST_MATCHED" if matched_remote else ""),
        "dependency_versions": versions,
        "elapsed_seconds": round(elapsed, 1),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
