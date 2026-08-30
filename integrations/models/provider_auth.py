"""Provider authentication policy helpers.

Remote providers remain credential-required by default. Explicit loopback
OpenAI-compatible endpoints may operate without bearer auth so local Ollama,
vLLM, and similar servers work without fake API keys.
"""

from __future__ import annotations

import urllib.parse
from typing import Optional


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_loopback_base_url(base_url: Optional[str]) -> bool:
    """Return True only for explicit HTTP(S) loopback endpoints.

    This is deliberately conservative because the result controls whether bearer
    authentication may be omitted. Canonical URL validation still remains the
    primary URL authority, but this helper independently rejects alternate
    schemes, embedded credentials, malformed ports, percent-encoded netlocs,
    and non-loopback hosts as defense in depth.
    """
    if not base_url or not isinstance(base_url, str):
        return False
    cleaned = base_url.strip()
    if not cleaned or any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t")):
        return False
    try:
        parsed = urllib.parse.urlparse(cleaned)
        if parsed.scheme.lower() not in ("http", "https"):
            return False
        netloc = parsed.netloc or ""
        if not netloc or "%" in netloc or "@" in netloc or parsed.username or parsed.password:
            return False
        # Force malformed ports to fail closed.
        _ = parsed.port
    except Exception:
        return False

    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    if not hostname:
        return False
    return bool(
        hostname in LOOPBACK_HOSTS
        or hostname.endswith(".localhost")
    )


def provider_requires_api_key(adapter_type: str, base_url: Optional[str]) -> bool:
    """Fail-closed credential policy for provider configuration.

    Gemini/native providers and all remote OpenAI-compatible endpoints require a
    credential. Only explicit loopback OpenAI-compatible endpoints may omit it.
    """
    adapter = str(adapter_type or "").strip().upper()
    if adapter in ("OPENAI_COMPATIBLE", "OPENAI"):
        return not is_loopback_base_url(base_url)
    return True
