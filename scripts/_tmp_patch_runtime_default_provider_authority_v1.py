from pathlib import Path

path = Path("config/authority.py")
text = path.read_text(encoding="utf-8")

replacements = [
    ('    default_provider: str = "gemini"\n', '    default_provider: str = "xkiro"\n'),
    ('        raw_provider, prov["DEFAULT_PROVIDER"] = self._get_with_provenance("DEFAULT_PROVIDER", "gemini")\n', '        raw_provider, prov["DEFAULT_PROVIDER"] = self._get_with_provenance("DEFAULT_PROVIDER", "xkiro")\n'),
]

for old, new in replacements:
    old_count = text.count(old)
    new_count = text.count(new)
    if old_count == 1 and new_count == 0:
        text = text.replace(old, new, 1)
    elif old_count == 0 and new_count == 1:
        pass
    else:
        raise SystemExit(
            f"fail-closed replacement mismatch: old_count={old_count}, new_count={new_count}, old={old!r}"
        )

path.write_text(text, encoding="utf-8")
print("applied runtime default provider authority patch")
