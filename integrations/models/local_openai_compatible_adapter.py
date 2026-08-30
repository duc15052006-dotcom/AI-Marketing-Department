"""Loopback-only OpenAI-compatible adapter variant.

This class exists solely so validated local Ollama/vLLM/LiteLLM-style servers
can run without fake bearer credentials. Registry policy decides when it may be
used; remote endpoints continue using the credential-required base adapter.
"""

from __future__ import annotations

from integrations.models.openai_compatible_adapter import OpenAICompatibleProviderAdapter


class LocalNoAuthOpenAICompatibleProviderAdapter(OpenAICompatibleProviderAdapter):
    """OpenAI-compatible adapter whose configuration does not require an API key."""

    def is_configured(self) -> bool:
        return True
