from pathlib import Path

path = Path("tests/test_prod_model_settings_01.py")
text = path.read_text(encoding="utf-8")

upper = text.count("STRATEGIST")
lower = text.count("strategist")
if upper != 4:
    raise SystemExit(f"Expected exactly 4 uppercase STRATEGIST current-contract references, found {upper}")
if lower != 2:
    raise SystemExit(f"Expected exactly 2 lowercase strategist current-contract references, found {lower}")

text = text.replace("STRATEGIST", "CONTENT")
text = text.replace("strategist", "content")
text = text.replace("prov_strat", "prov_content")
text = text.replace("m-strat", "m-content")

if "STRATEGIST" in text or "strategist" in text:
    raise SystemExit("Stale Strategist current-contract reference remains in model settings regression")

path.write_text(text, encoding="utf-8")
print("Migrated model settings regression to canonical CONTENT contract")
