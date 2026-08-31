from pathlib import Path

path = Path("runtime/engine.py")
text = path.read_text(encoding="utf-8")
original = text

old_default = '            pol_dict = {"free_only_mode": True, "timeout": 60.0}\n'
new_default = '            pol_dict = {"free_only_mode": True, "timeout_seconds": 60.0}\n'
if text.count(old_default) != 1:
    raise SystemExit(f"DEFAULT_PIN_ANCHOR_COUNT={text.count(old_default)}")
text = text.replace(old_default, new_default, 1)

start_anchor = "            raw_pol = context.model_policy\n"
end_anchor = '            if "providers" in raw_pol and isinstance(raw_pol["providers"], dict):\n'
if text.count(start_anchor) != 1:
    raise SystemExit(f"POLICY_START_ANCHOR_COUNT={text.count(start_anchor)}")
if text.count(end_anchor) != 1:
    raise SystemExit(f"POLICY_END_ANCHOR_COUNT={text.count(end_anchor)}")
start = text.index(start_anchor)
end = text.index(end_anchor, start)

new_policy_block = '''            raw_pol = context.model_policy
            if not isinstance(raw_pol, dict):
                raise RuntimeError(
                    "RUN_PINNED_MODEL_CONFIGURATION_INVALID: Pinned ModelPolicy payload must be a mapping."
                )

            if "policy" in raw_pol:
                if not isinstance(raw_pol.get("policy"), dict):
                    raise RuntimeError(
                        "RUN_PINNED_MODEL_CONFIGURATION_INVALID: 'policy' must be a mapping."
                    )
                pol_dict = dict(raw_pol["policy"])
            else:
                pol_dict = dict(raw_pol)

            try:
                from integrations.models.registry import ModelPolicy

                # Explicit compatibility for the historical runtime pin key.
                # Canonical policy uses timeout_seconds; unrelated legacy keys
                # are ignored, while malformed recognized governance fields
                # still fail closed inside ModelPolicy validation.
                if "timeout" in pol_dict and "timeout_seconds" not in pol_dict:
                    pol_dict["timeout_seconds"] = pol_dict["timeout"]
                pol_dict.pop("timeout", None)

                valid_keys = set(getattr(ModelPolicy, "__dataclass_fields__", {}).keys())
                if not valid_keys:
                    raise ValueError("MODEL_POLICY_SCHEMA_FIELDS_UNAVAILABLE")
                filtered_pol = {k: v for k, v in pol_dict.items() if k in valid_keys}
                if pol_dict and not filtered_pol:
                    raise ValueError("NO_RECOGNIZED_MODEL_POLICY_FIELDS")
                if filtered_pol:
                    model_policy_obj = ModelPolicy(**filtered_pol)
            except Exception as exc:
                raise RuntimeError(
                    f"RUN_PINNED_MODEL_CONFIGURATION_INVALID: Failed to reconstruct pinned ModelPolicy: {exc}"
                ) from exc
'''
text = text[:start] + new_policy_block + text[end:]

if text == original:
    raise SystemExit("NO_CHANGE")
if '"free_only_mode": True, "timeout": 60.0' in text:
    raise SystemExit("LEGACY_DEFAULT_TIMEOUT_REMAINS")
if 'ModelPolicy.model_fields' in text:
    raise SystemExit("PYDANTIC_MODEL_FIELDS_PATH_REMAINS")

path.write_text(text, encoding="utf-8")
