from pathlib import Path

path = Path("integrations/models/gateway.py")
text = path.read_text(encoding="utf-8")

old = '''        # Authoritative Model Policy
        self._has_explicit_policy: bool = model_policy is not None
        self._model_policy = model_policy or ModelPolicy(
            global_target=ModelTarget(provider_id=default_provider or "xkiro", model_id="mistralai/mistral-large-2512"),
            fallback_chain=[
                ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),
                ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),
            ],
            free_only_mode=self._free_only_mode,
        )
'''

new = '''        # Authoritative Model Policy
        self._has_explicit_policy: bool = model_policy is not None
        if model_policy is not None:
            self._model_policy = model_policy
        else:
            # The implicit policy must honor the configured default provider and
            # must not silently inject vendor-specific model IDs or fallbacks.
            # Settings / explicit ModelPolicy remains the authority for fallback.
            provider_definition = self.provider_registry.get_provider(self._default_provider)
            implicit_model = (
                provider_definition.default_model
                if provider_definition is not None and provider_definition.default_model
                else "default"
            )
            self._model_policy = ModelPolicy(
                global_target=ModelTarget(
                    provider_id=self._default_provider,
                    model_id=implicit_model,
                ),
                fallback_chain=[],
                free_only_mode=self._free_only_mode,
            )
'''

old_count = text.count(old)
new_count = text.count(new)
if old_count == 1 and new_count == 0:
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("applied production patch")
elif old_count == 0 and new_count == 1:
    print("production patch already present")
else:
    raise SystemExit(f"fail-closed: old_count={old_count}, new_count={new_count}")
