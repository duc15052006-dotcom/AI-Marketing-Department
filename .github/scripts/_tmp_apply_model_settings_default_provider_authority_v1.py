from pathlib import Path

path = Path('integrations/models/settings_manager.py')
text = path.read_text(encoding='utf-8')

replacements = [
    (
        'default_factory=lambda: ModelTarget(provider_id="gemini", model_id="gemini-flash-latest")',
        'default_factory=lambda: ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512")',
    ),
    (
        'global_target=ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),\n                fallback_chain=[\n                    ModelTarget(provider_id="thespark", model_id="spark-default"),\n                    ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),\n                ],',
        'global_target=ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),\n                fallback_chain=[],',
    ),
]

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'fail-closed: expected exactly one settings authority block, found {count}')
    text = text.replace(old, new)

path.write_text(text, encoding='utf-8')
print('patched model settings default provider authority')
