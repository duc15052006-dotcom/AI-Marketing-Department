"""Filesystem Containment and Path Security Primitive (PROD-FS-01).

Enforces strict sandbox containment for all local filesystem operations:
- Pre-resolution lexical validation preventing SMB/network probe, ADS, device names, and drive escapes
- Canonical path resolution and hierarchical containment verification (is_relative_to / normcase)
- Safe read and write resolution with directory hierarchy auditing
- Symlink and directory junction escape blocking
- Zero absolute path leakage in error messages
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Optional, Set, Tuple, Union

WINDOWS_RESERVED_NAMES: Set[str] = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
    "CONIN$",
    "CONOUT$",
}


class FilesystemSecurityError(Exception):
    """Exception raised when an untrusted path violates filesystem containment or lexical safety."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def validate_lexical_path(raw_path: Any) -> str:
    """Perform pre-resolution lexical security validation on an untrusted path.

    Blocks:
    - Non-string or empty inputs
    - Null bytes (\x00)
    - UNC / Network paths (\\\\server\\share, //server/share)
    - Windows device / Extended paths (\\\\?\\, \\\\.\\)
    - Absolute paths (C:\\..., /..., \\...)
    - Windows drive-relative paths (C:foo)
    - Alternate Data Streams (file.txt:stream, ::$DATA)
    - Windows reserved device names (CON, NUL, AUX, PRN, COM1..9, LPT1..9)
    """
    if not isinstance(raw_path, str):
        raise FilesystemSecurityError("INVALID_PATH", "Path must be a non-empty string.")

    cleaned = raw_path.strip()
    if not cleaned:
        raise FilesystemSecurityError("INVALID_PATH", "Path cannot be empty.")

    if "\x00" in cleaned:
        raise FilesystemSecurityError("INVALID_PATH", "Null bytes are not permitted in path.")

    # 1. UNC / Network Path Checks
    posix_normalized = cleaned.replace("\\", "/")
    if (
        posix_normalized.startswith("//")
        or cleaned.startswith(("\\\\", "//", "\\/", "/\\"))
        or cleaned.startswith(("\\\\?\\UNC", "\\\\.\\UNC", "//?/UNC", "//./UNC"))
    ):
        raise FilesystemSecurityError("UNC_PATH_FORBIDDEN", "Network and UNC paths are forbidden.")

    # 2. Windows Device / Extended Path Prefixes
    if (
        cleaned.startswith(("\\\\?\\", "\\\\.\\", "//?/", "//./"))
        or "\\?\\" in cleaned
        or "//?/" in cleaned
        or "\\.\\" in cleaned
        or "//./" in cleaned
    ):
        raise FilesystemSecurityError("UNC_PATH_FORBIDDEN", "Windows device and extended paths are forbidden.")

    # 3. Absolute Path Checks
    if posix_normalized.startswith("/"):
        raise FilesystemSecurityError("ABSOLUTE_PATH_FORBIDDEN", "Absolute paths are forbidden.")

    if cleaned.startswith("\\"):
        raise FilesystemSecurityError("ABSOLUTE_PATH_FORBIDDEN", "Root-relative paths are forbidden.")

    if re.match(r"^[a-zA-Z]:[/\\]", cleaned):
        raise FilesystemSecurityError("ABSOLUTE_PATH_FORBIDDEN", "Absolute drive paths are forbidden.")

    # 4. Windows Drive-Relative Path Checks (e.g. C:foo.txt)
    if re.match(r"^[a-zA-Z]:[^/\\]", cleaned):
        raise FilesystemSecurityError("ABSOLUTE_PATH_FORBIDDEN", "Drive-relative paths are forbidden.")

    # 5. Alternate Data Stream (ADS) Checks
    if ":" in cleaned:
        raise FilesystemSecurityError("INVALID_PATH", "Alternate data stream (ADS) syntax is forbidden.")

    # 6. Windows Reserved Device Names
    parts = re.split(r"[/\\]+", cleaned)
    for part in parts:
        seg = part.strip()
        if not seg or seg in (".", ".."):
            continue
        stem = seg.split(".")[0].strip().upper()
        if stem in WINDOWS_RESERVED_NAMES:
            raise FilesystemSecurityError("INVALID_PATH", f"Windows reserved device name '{stem}' is forbidden.")

    return cleaned


def is_path_contained(candidate: Path, canonical_root: Path) -> bool:
    """Verify that candidate path is hierarchically inside canonical root without string prefix flaws."""
    try:
        c_resolved = candidate.resolve()
        r_resolved = canonical_root.resolve()

        c_norm = Path(os.path.normcase(str(c_resolved)))
        r_norm = Path(os.path.normcase(str(r_resolved)))

        return c_norm == r_norm or c_norm.is_relative_to(r_norm)
    except Exception:
        return False


def resolve_safe_path(
    root: Union[str, Path],
    untrusted_path: Any,
    operation: str = "read",
) -> Path:
    """Resolve an untrusted user/model path safely within configured root.

    Args:
        root: Configured base directory for the capability.
        untrusted_path: User, model, or API supplied path parameter.
        operation: 'read' (must exist and be contained) or 'write' (parent hierarchy contained).

    Returns:
        Canonical Path object guaranteed to reside within root.

    Raises:
        FilesystemSecurityError: On lexical violations, traversal attempts, or missing read targets.
    """
    if root is None:
        raise FilesystemSecurityError("INVALID_ROOT", "Filesystem root cannot be None.")

    canonical_root = Path(root).resolve()
    if not canonical_root.exists() or not canonical_root.is_dir():
        canonical_root.mkdir(parents=True, exist_ok=True)

    validated_lexical = validate_lexical_path(untrusted_path)
    platform_neutral_lexical = validated_lexical.replace("\\", "/")

    if operation == "read":
        # Resolve target relative to canonical root
        try:
            target = (canonical_root / platform_neutral_lexical).resolve()
        except Exception as e:
            raise FilesystemSecurityError("INVALID_PATH", f"Path resolution failed: {e}")

        # Containment check (evaluates real target after resolving symlinks/junctions)
        if not is_path_contained(target, canonical_root):
            raise FilesystemSecurityError(
                "PATH_OUTSIDE_ALLOWED_ROOT",
                "Path escapes configured filesystem root.",
            )

        if not target.exists():
            raise FilesystemSecurityError("FILE_NOT_FOUND", f"File not found: {untrusted_path}")

        if not target.is_file():
            raise FilesystemSecurityError("READ_ERROR", f"Target path is not a regular file: {untrusted_path}")

        return target

    elif operation == "write":
        # Lexical path composition
        try:
            unresolved_target = canonical_root / platform_neutral_lexical
        except Exception as e:
            raise FilesystemSecurityError("INVALID_PATH", f"Path construction failed: {e}")

        # Find the existing ancestor directory chain to resolve symlinks/junctions in the path
        curr = unresolved_target.parent
        uncreated_parts = [unresolved_target.name]
        while not curr.exists() and curr != canonical_root and curr != curr.parent:
            uncreated_parts.append(curr.name)
            curr = curr.parent

        try:
            resolved_ancestor = curr.resolve()
        except Exception as e:
            raise FilesystemSecurityError("INVALID_PATH", f"Ancestor resolution failed: {e}")

        if not is_path_contained(resolved_ancestor, canonical_root):
            raise FilesystemSecurityError(
                "PATH_OUTSIDE_ALLOWED_ROOT",
                "Target parent directory escapes configured filesystem root.",
            )

        # Assemble full target path from resolved ancestor
        final_candidate = resolved_ancestor
        for part in reversed(uncreated_parts):
            final_candidate = final_candidate / part

        if not is_path_contained(final_candidate, canonical_root):
            raise FilesystemSecurityError(
                "PATH_OUTSIDE_ALLOWED_ROOT",
                "Target path escapes configured filesystem root.",
            )

        return final_candidate

    else:
        raise FilesystemSecurityError("INVALID_OPERATION", f"Unknown operation: {operation}")
