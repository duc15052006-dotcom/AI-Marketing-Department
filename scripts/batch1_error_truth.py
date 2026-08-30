from pathlib import Path

path = Path("integrations/models/gateway.py")
text = path.read_text(encoding="utf-8")

anchor = '''def model_response_to_stream_error(\n    response: ModelResponse,\n    provider_name: str = "provider",\n) -> ModelStreamError:\n'''
helper = '''def _public_safe_message_for_code(code: str, provider_name: str = "provider") -> str:\n    """Return a bounded user-safe message without reflecting raw transport/provider detail."""\n    messages = {\n        "RATE_LIMITED": "The model provider rate limit was reached. Please try again later.",\n        "AUTH_ERROR": "The model provider rejected the configured credential.",\n        "AUTHORIZATION_ERROR": "The model provider denied access to this request.",\n        "PROVIDER_ACCESS_DENIED": "The model provider denied access to this request.",\n        "TIMEOUT": "The model provider request timed out.",\n        "NETWORK_ERROR": "The model provider could not be reached.",\n        "PROVIDER_UNAVAILABLE": "The model provider is currently unavailable.",\n        "NO_CREDENTIAL": "No credential is configured for the selected model provider.",\n        "PROVIDER_DISABLED": "The selected model provider is disabled.",\n        "MODEL_NOT_FOUND": "The selected model is not available from the provider.",\n        "INVALID_REQUEST": "The model provider rejected the request configuration.",\n        "REQUEST_SCHEMA_ERROR": "The model request did not match the required schema.",\n        "STREAM_UNSUPPORTED": "The selected model provider does not support streaming for this request.",\n        "PROVIDER_RESPONSE_ERROR": "The model provider request failed.",\n    }\n    return messages.get(code, "The model provider request failed.")\n\n\n'''
if helper not in text:
    if anchor not in text:
        raise SystemExit("batch1: model_response_to_stream_error anchor not found")
    text = text.replace(anchor, helper + anchor, 1)

old = '''        safe_msg = meta.get("safe_message") or sanitize_secrets(response.error or f"Error from {provider_name}")\n'''
new = '''        raw_safe_msg = meta.get("safe_message")\n        safe_msg = sanitize_secrets(str(raw_safe_msg)) if isinstance(raw_safe_msg, str) and raw_safe_msg.strip() else _public_safe_message_for_code(code, provider_name)\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("batch1: trusted metadata safe-message anchor not found")

old = '''    # 2. Structural status signal\n    status = getattr(response, "status", None)\n    clean_err = sanitize_secrets(response.error or f"Error from {provider_name}")\n\n    if status == ModelResponseStatus.RATE_LIMITED:\n'''
new = '''    # 2. Structural status signal. Raw response.error is diagnostic/internal and\n    # must never be reflected to public/UI boundaries.\n    status = getattr(response, "status", None)\n\n    if status == ModelResponseStatus.RATE_LIMITED:\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise SystemExit("batch1: structural status anchor not found")

replacements = {
    'safe_message=clean_err,\n            retryable=True,\n            http_status=429,': 'safe_message=_public_safe_message_for_code("RATE_LIMITED", provider_name),\n            retryable=True,\n            http_status=429,',
    'safe_message=clean_err,\n            retryable=True,\n            http_status=408,': 'safe_message=_public_safe_message_for_code("TIMEOUT", provider_name),\n            retryable=True,\n            http_status=408,',
    'safe_message=clean_err,\n            retryable=False,\n            http_status=None,\n        )\n    else:\n        # Conservative canonical provider error without string guessing\n        return ModelStreamError(\n            code="PROVIDER_RESPONSE_ERROR",\n            category="RESPONSE_ERROR",\n            safe_message=clean_err,': 'safe_message=_public_safe_message_for_code("STREAM_UNSUPPORTED", provider_name),\n            retryable=False,\n            http_status=None,\n        )\n    else:\n        # Conservative canonical provider error without string guessing or raw-detail reflection.\n        return ModelStreamError(\n            code="PROVIDER_RESPONSE_ERROR",\n            category="RESPONSE_ERROR",\n            safe_message=_public_safe_message_for_code("PROVIDER_RESPONSE_ERROR", provider_name),',
}
for old_snip, new_snip in replacements.items():
    if old_snip in text:
        text = text.replace(old_snip, new_snip, 1)
    elif new_snip not in text:
        raise SystemExit(f"batch1: replacement anchor missing: {old_snip[:60]}")

path.write_text(text, encoding="utf-8")
print("batch1 error-truth patch applied")
