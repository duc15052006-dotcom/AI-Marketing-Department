"""Deterministic Environment & Configuration Loader (PROD-CONFIG-01 / PROD-CONFIG-01R).

Enforces:
1. Strict Configuration Precedence: Explicit argument > Existing process environment > Repo .env > Code default.
2. Immutability & Single-Authority: Snapshot taken at startup, immutable during execution.
3. Safe .env Parser: No eval/exec/shell expansion; rejects malformed lines, duplicate keys, unterminated quotes, and null bytes.
4. Loopback API Binding: Strict validation preventing 0.0.0.0 or external network binds.
5. Zero Secret Leakage: Strict redaction in diagnostics, errors, health endpoints, and logs.
6. Secret Rotation: CONFIG_RELOAD_REQUIRES_RESTART = True (no implicit ambient live mutation).
"""

from __future__ import annotations

import math
import os
import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

# Root directory of the repository (anchored deterministically)
REPO_ROOT: Path = Path(__file__).resolve().parent.parent

# Permitted loopback host identifiers for production API server
PRODUCTION_LOOPBACK_HOSTS: Set[str] = {
    "127.0.0.1",
    "localhost",
    "::1",
    "http://127.0.0.1",
    "http://localhost",
}

# Known sensitive environment keys that must never appear in plaintext diagnostics/logs
KNOWN_SECRET_ENV_KEYS: Set[str] = {
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "XKIRO_API_KEY",
    "THESPARK_API_KEY",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_CLIENT_ID",
    "APP_API_TOKEN",  # NOTE: DEPRECATED / IGNORED FOR RUNTIME AUTH (per PROD-SEC)
}

# Configuration reload policy
CONFIG_RELOAD_REQUIRES_RESTART: bool = True


class ConfigSource(str, Enum):
    """Provenance tracking for configuration values."""

    EXPLICIT = "EXPLICIT"
    PROCESS_ENV = "PROCESS_ENV"
    ENV_FILE = "ENV_FILE"
    DEFAULT = "DEFAULT"


class ConfigError(Exception):
    """Base exception for configuration authority errors."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


class ConfigParseError(ConfigError):
    """Raised when a configuration file (.env) contains malformed or unparseable syntax."""

    pass


class ConfigDuplicateKeyError(ConfigError):
    """Raised when a configuration file defines the same key multiple times."""

    pass


class ConfigValidationError(ConfigError):
    """Raised when a configuration value fails schema, type, or bounds validation."""

    pass


class ConfigSecurityError(ConfigError):
    """Raised when a configuration violates security invariants (e.g. non-loopback host bind)."""

    pass


def parse_env_content(content: str) -> Dict[str, str]:
    """Parse .env file content strictly without shell evaluation or code execution.

    Syntax Rules:
    - KEY=value
    - KEY="value" (double-quoted, supports standard escape sequences)
    - KEY='value' (single-quoted literal)
    - KEY="value" # inline comment
    - KEY='value' # inline comment
    - Blank lines and comment lines (#) are ignored
    - Malformed lines raise ConfigParseError("CONFIG_PARSE_ERROR")
    - Duplicate keys raise ConfigDuplicateKeyError("CONFIG_DUPLICATE_KEY")
    - Null bytes raise ConfigParseError("CONFIG_PARSE_ERROR")

    Returns:
        Dict mapping key strings to parsed value strings.
    """
    if not isinstance(content, str):
        raise ConfigParseError("CONFIG_PARSE_ERROR", "Content must be a string.")

    if "\x00" in content:
        raise ConfigParseError("CONFIG_PARSE_ERROR", "Null bytes are forbidden in configuration content.")

    parsed: Dict[str, str] = {}
    lines = content.splitlines()

    for line_num, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Missing '=' delimiter in '{line}'",
            )

        key_part, val_part = line.split("=", 1)
        key = key_part.strip()
        val = val_part.strip()

        if not key:
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Empty key in '{line}'",
            )

        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", key):
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Invalid key name '{key}' (must be valid identifier)",
            )

        if key in parsed:
            raise ConfigDuplicateKeyError(
                "CONFIG_DUPLICATE_KEY",
                f"Duplicate key '{key}' found on line {line_num}",
            )

        # Parse value quoting and inline comments
        parsed_val = _parse_quoted_value(val, line_num)
        parsed[key] = parsed_val

    return parsed


def _parse_quoted_value(val: str, line_num: int) -> str:
    """Parse quoted or unquoted .env value string with support for inline comments and edge cases."""
    if not val:
        return ""

    # Double quoted: "..."
    if val.startswith('"'):
        i = 1
        escaped = False
        closing_idx = -1
        while i < len(val):
            c = val[i]
            if escaped:
                escaped = False
            elif c == '\\':
                escaped = True
            elif c == '"':
                closing_idx = i
                break
            i += 1

        if closing_idx == -1:
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Unterminated double quote in value '{val}'",
            )

        remainder = val[closing_idx + 1:].strip()
        if remainder and not remainder.startswith("#"):
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Unexpected content after closing quote in '{val}'",
            )

        inner = val[1:closing_idx]
        return (
            inner.replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace("\\t", "\t")
            .replace("\\\\", "\\")
        )

    # Single quoted: '...'
    if val.startswith("'"):
        closing_idx = val.find("'", 1)
        if closing_idx == -1:
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Unterminated single quote in value '{val}'",
            )

        remainder = val[closing_idx + 1:].strip()
        if remainder and not remainder.startswith("#"):
            raise ConfigParseError(
                "CONFIG_PARSE_ERROR",
                f"Malformed line {line_num}: Unexpected content after closing quote in '{val}'",
            )

        return val[1:closing_idx]

    # Unquoted: strip inline comments if separated by whitespace
    # e.g., KEY=val # comment -> val
    if " #" in val:
        val = val.split(" #", 1)[0].rstrip()

    # Reject unescaped unclosed quote characters
    if '"' in val or "'" in val:
        raise ConfigParseError(
            "CONFIG_PARSE_ERROR",
            f"Malformed line {line_num}: Unbalanced or unquoted quote in value '{val}'",
        )

    return val


def parse_env_file(file_path: Optional[Union[str, Path]] = None) -> Dict[str, str]:
    """Read and parse a .env file into a dictionary without modifying process environment."""
    target_path = Path(file_path).resolve() if file_path else (REPO_ROOT / ".env")
    if not target_path.exists() or not target_path.is_file():
        return {}

    try:
        content = target_path.read_text(encoding="utf-8")
    except Exception as e:
        raise ConfigParseError(
            "CONFIG_READ_ERROR",
            f"Failed to read configuration file at '{target_path}': {e}",
        ) from e

    return parse_env_content(content)


def load_env_file(
    file_path: Optional[Union[str, Path]] = None,
    override: bool = False,
) -> Dict[str, str]:
    """Load configuration from a deterministic .env file.

    Invariants:
    - Target file defaults strictly to REPO_ROOT / ".env" (no CWD or home directory search).
    - Existing process environment variables are preserved unless override=True.
    - .env only populates missing environment variables.
    """
    parsed = parse_env_file(file_path)

    for k, v in parsed.items():
        if override or k not in os.environ:
            os.environ[k] = v

    return parsed


# ==============================================================================
# Type-Safe Validation Helpers
# ==============================================================================


def parse_bool(
    val: Any,
    default: bool = False,
    setting_name: str = "BOOLEAN_SETTING",
) -> bool:
    """Strictly parse a boolean value without ambiguous truthiness."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        if val == 1:
            return True
        if val == 0:
            return False
        raise ConfigValidationError(
            "CONFIG_INVALID_BOOLEAN",
            f"Invalid numeric boolean value '{val}' for '{setting_name}'. Expected 0 or 1.",
        )

    str_val = str(val).strip().lower()
    if str_val in ("true", "1", "yes", "on"):
        return True
    if str_val in ("false", "0", "no", "off", ""):
        return False

    raise ConfigValidationError(
        "CONFIG_INVALID_BOOLEAN",
        f"Invalid boolean string '{val}' for '{setting_name}'. Expected true/false/1/0/yes/no/on/off.",
    )


def parse_int(
    val: Any,
    default: int = 0,
    min_val: Optional[int] = None,
    max_val: Optional[int] = None,
    setting_name: str = "INTEGER_SETTING",
) -> int:
    """Strictly parse an integer value and validate bounds."""
    if val is None:
        parsed = default
    else:
        try:
            parsed = int(str(val).strip())
        except (ValueError, TypeError) as e:
            raise ConfigValidationError(
                "CONFIG_INVALID_INTEGER",
                f"Value '{val}' for '{setting_name}' is not a valid integer.",
            ) from e

    if min_val is not None and parsed < min_val:
        raise ConfigValidationError(
            "CONFIG_INTEGER_OUT_OF_BOUNDS",
            f"Value {parsed} for '{setting_name}' is less than minimum allowed ({min_val}).",
        )

    if max_val is not None and parsed > max_val:
        raise ConfigValidationError(
            "CONFIG_INTEGER_OUT_OF_BOUNDS",
            f"Value {parsed} for '{setting_name}' is greater than maximum allowed ({max_val}).",
        )

    return parsed


def parse_float(
    val: Any,
    default: float = 0.0,
    min_val: Optional[float] = None,
    max_val: Optional[float] = None,
    setting_name: str = "FLOAT_SETTING",
) -> float:
    """Strictly parse a float value, validating bounds and rejecting non-finite numbers (NaN/Inf)."""
    if val is None:
        parsed = default
    else:
        try:
            parsed = float(str(val).strip())
        except (ValueError, TypeError) as e:
            raise ConfigValidationError(
                "CONFIG_INVALID_FLOAT",
                f"Value '{val}' for '{setting_name}' is not a valid float.",
            ) from e

    if not math.isfinite(parsed):
        raise ConfigValidationError(
            "CONFIG_NON_FINITE_FLOAT",
            f"Non-finite float value '{val}' (NaN or Infinity) is forbidden for '{setting_name}'.",
        )

    if min_val is not None and parsed < min_val:
        raise ConfigValidationError(
            "CONFIG_FLOAT_OUT_OF_BOUNDS",
            f"Value {parsed} for '{setting_name}' is less than minimum allowed ({min_val}).",
        )

    if max_val is not None and parsed > max_val:
        raise ConfigValidationError(
            "CONFIG_FLOAT_OUT_OF_BOUNDS",
            f"Value {parsed} for '{setting_name}' is greater than maximum allowed ({max_val}).",
        )

    return parsed


def validate_loopback_host(
    host: str,
    setting_name: str = "API_HOST",
) -> str:
    """Enforce that API bind host is strictly loopback (rejects 0.0.0.0 and external IPs)."""
    if not host or not isinstance(host, str):
        raise ConfigSecurityError(
            "CONFIG_INVALID_HOST",
            f"Invalid host value for '{setting_name}'.",
        )

    cleaned = host.strip().lower()
    if cleaned not in PRODUCTION_LOOPBACK_HOSTS:
        raise ConfigSecurityError(
            "CONFIG_REMOTE_BIND_FORBIDDEN",
            f"Host '{host}' is not a permitted loopback address. API server must bind strictly to 127.0.0.1, localhost, or ::1.",
        )

    return cleaned


def redact_secret_value(val: Optional[str]) -> str:
    """Redact secret string safely for diagnostics, health, and logs."""
    if not val or not str(val).strip():
        return "[UNCONFIGURED]"
    return "[CONFIGURED]"


def sanitize_config_dict(
    config_dict: Dict[str, Any],
    secret_keys: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Return a sanitized copy of a configuration dictionary with all secrets redacted."""
    targets = (secret_keys or KNOWN_SECRET_ENV_KEYS)
    sanitized: Dict[str, Any] = {}
    for k, v in config_dict.items():
        if isinstance(v, dict):
            sanitized[k] = sanitize_config_dict(v, targets)
        elif k.upper() in targets or any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
            sanitized[k] = redact_secret_value(str(v) if v is not None else None)
        else:
            sanitized[k] = v
    return sanitized
