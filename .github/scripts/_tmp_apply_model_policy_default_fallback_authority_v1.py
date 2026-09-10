from pathlib import Path

path = Path('integrations/models/registry.py')
text = path.read_text(encoding='utf-8')
old = '''    fallback_chain: List[ModelTarget] = Field(\n        default_factory=lambda: [\n            ModelTarget(provider_id="xkiro", model_id="mistralai/mistral-large-2512"),\n            ModelTarget(provider_id="gemini", model_id="gemini-flash-latest"),\n        ]\n    )'''
new = '''    fallback_chain: List[ModelTarget] = Field(default_factory=list)'''
count = text.count(old)
if count != 1:
    raise SystemExit(f'fail-closed: expected exactly one ModelPolicy fallback block, found {count}')
path.write_text(text.replace(old, new), encoding='utf-8')
print('patched ModelPolicy fallback authority')
