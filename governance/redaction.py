"""Shared fail-closed redaction helpers for persisted/public diagnostics.

This module is deliberately dependency-light so model, tool, API, and governance
layers can sanitize diagnostics without creating circular imports.
"""

from __future__ import annotations

import re
from typing import Any, Optional

REDACTED_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "authorization",
    "auth_token",
    "access_token",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "private_key",
    "secret_key",
    "session_token",
    "refresh_token",
    "client_secret",
}


def sanitize_sensitive_text(text: Any, secret: Optional[str] = None) -> str:
    """Return a bounded-scope diagnostic string with credential material redacted.

    ``secret`` may be supplied by code that already holds the exact transient
    credential. Generic patterns provide defense in depth for callers that do not.
    """
    if text is None:
        return ""

    sanitized = str(text)
    if secret and str(secret).strip():
        sanitized = sanitized.replace(str(secret).strip(), "[REDACTED_SECRET]")

    # Authorization headers / inline auth values.
    sanitized = re.sub(
        r"((?:Authorization\s*:\s*)?Bearer\s+)[^\s,;}{\"']+",
        r"\1[REDACTED_TOKEN]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"((?:Authorization\s*:\s*)?Basic\s+)[^\s,;}{\"']+",
        r"\1[REDACTED_BASIC_AUTH]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Query-string credentials in URLs.
    sanitized = re.sub(
        r"([?&](?:api[_\-]?key|apikey|access[_\-]?token|token|secret|password|client_secret)=)[^&\s]+",
        r"\1[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Quoted JSON/dict/config assignments.
    sanitized = re.sub(
        r"([\"']?(?:api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|refresh[_\-]?token|token|secret|password|client[_\-]?secret)[\"']?\s*[:=]\s*[\"'])([^\"'\r\n]+)([\"'])",
        r"\1[REDACTED]\3",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Unquoted assignments.
    sanitized = re.sub(
        r"([\"']?(?:api[_\-]?key|apikey|access[_\-]?token|auth[_\-]?token|refresh[_\-]?token|token|secret|password|client[_\-]?secret)[\"']?\s*[:=]\s*)([^\s,;}{\"'&?]+)",
        r"\1[REDACTED]",
        sanitized,
        flags=re.IGNORECASE,
    )

    # Common credential prefixes that may appear without a key name.
    generic_token_patterns = (
        r"\bsk-[A-Za-z0-9_\-]{8,}\b",
        r"\bAIza[A-Za-z0-9_\-]{16,}\b",
        r"\bgh[pousr]_[A-Za-z0-9_]{12,}\b",
        r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b",
    )
    for pattern in generic_token_patterns:
        sanitized = re.sub(pattern, "[REDACTED_TOKEN]", sanitized)

    return sanitized


def sanitize_sensitive_payload(obj: Any) -> Any:
    """Recursively redact sensitive fields and strings in diagnostic payloads."""
    if isinstance(obj, dict):
        sanitized = {}
        for key, value in obj.items():
            key_lower = str(key).lower()
            if (
                key_lower in REDACTED_SENSITIVE_KEYS
                or any(
                    fragment in key_lower
                    for fragment in (
                        "password",
                        "secret",
                        "api_key",
                        "apikey",
                        "auth_token",
                        "access_token",
                        "refresh_token",
                        "client_secret",
                    )
                )
            ):
                sanitized[key] = "[REDACTED_SECRET]"
            else:
                sanitized[key] = sanitize_sensitive_payload(value)
        return sanitized
    if isinstance(obj, list):
        return [sanitize_sensitive_payload(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_sensitive_payload(item) for item in obj)
    if isinstance(obj, str):
        return sanitize_sensitive_text(obj)
    return obj
