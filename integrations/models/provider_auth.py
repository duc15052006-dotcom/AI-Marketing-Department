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
    """Return True only for explicit loopback hostnames/addresses.

    This helper does not make an invalid URL valid; callers should still run the
    repository's canonical base-URL validator before constructing adapters.
    """
    if not base_url or not isinstance(base_url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(base_url.strip())
    except Exception:
        return False
    hostname = (parsed.hostname or "").strip().lower().rstrip(".")
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
