"""Loopback-only OpenAI-compatible adapter variant.

This class exists solely so validated local Ollama/vLLM/LiteLLM-style servers
can run without fake bearer credentials. Registry policy decides when it may be
used; remote endpoints continue using the credential-required base adapter.
"""

from __future__ import annotations

from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter
from integrations.models.provider_auth import is_loopback_base_url


class LocalNoAuthOpenAICompatibleProviderAdapter(OpenAICompatibleProviderAdapter):
    """OpenAI-compatible adapter that permits no bearer key only on loopback."""

    def __init__(self, *args, **kwargs) -> None:
        base_url = kwargs.get("base_url")
        if base_url is None and len(args) >= 2:
            base_url = args[1]
        if not is_loopback_base_url(base_url):
            raise ValueError(
                "LOCAL_NO_AUTH_REQUIRES_LOOPBACK: No-auth OpenAI-compatible providers "
                "must use localhost, 127.0.0.1, ::1, or a .localhost hostname."
            )
        super().__init__(*args, **kwargs)

    def is_configured(self) -> bool:
        return True
