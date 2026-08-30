from pathlib import Path

# ---------------------------------------------------------------------------
# 1) Gateway: machine error truth remains canonical and raw provider detail is
# never promoted to public/UI safe_message.
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 2) Chat UX: localize only the user-facing wrapper from canonical public
# fields. Never parse response.error or exception strings to infer cause.
# ---------------------------------------------------------------------------
path = Path("chat/engine.py")
text = path.read_text(encoding="utf-8")

method_anchor = "    def generate_chat_response(\n"
helper_method = '''    @staticmethod\n    def _format_public_failure(user_message: str, public_error: Any) -> str:\n        """Render a language-appropriate failure from canonical public fields only."""\n        from chat.router import normalize_for_routing\n\n        norm = normalize_for_routing(user_message or "")\n        tokens = set(norm.split())\n        vi_markers = {\n            "toi", "ban", "cho", "la", "gi", "khong", "hay", "phan", "tich",\n            "so", "lieu", "giai", "thich", "tim", "nghien", "cuu", "muc", "do",\n            "tang", "truong", "nganh", "thanh", "bang", "giup", "minh",\n        }\n        is_vietnamese = bool(tokens & vi_markers) or any(\n            ch in (user_message or "")\n            for ch in "ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"\n        )\n\n        if not is_vietnamese:\n            safe = getattr(public_error, "safe_message", "") or "The model request could not be completed."\n            return f"⚠️ Unable to complete the response: {safe}\\nYour message was kept in this chat session."\n\n        code = str(getattr(public_error, "code", "") or "")\n        category = str(getattr(public_error, "category", "") or "")\n        if code == "RATE_LIMITED" or category == "RATE_LIMIT":\n            detail = "Nhà cung cấp mô hình AI đang giới hạn tần suất yêu cầu. Vui lòng thử lại sau."\n        elif code in {"AUTH_ERROR", "AUTHORIZATION_ERROR", "PROVIDER_ACCESS_DENIED"} or category in {"AUTHENTICATION", "AUTHORIZATION"}:\n            detail = "Không thể xác thực quyền truy cập tới nhà cung cấp mô hình AI. Hãy kiểm tra cấu hình provider/API trong Settings."\n        elif code == "TIMEOUT" or category == "TIMEOUT":\n            detail = "Yêu cầu tới mô hình AI đã hết thời gian chờ. Bạn có thể thử lại."\n        elif code in {"NETWORK_ERROR", "PROVIDER_UNAVAILABLE"} or category == "NETWORK":\n            detail = "Không thể kết nối đến nhà cung cấp mô hình AI lúc này. Bạn có thể thử lại sau."\n        elif code in {"NO_CREDENTIAL", "PROVIDER_DISABLED", "MODEL_NOT_FOUND"} or category == "CONFIGURATION":\n            detail = "Cấu hình mô hình AI hiện chưa sẵn sàng. Hãy kiểm tra provider, model và API trong Settings."\n        elif category in {"STREAM_PROTOCOL", "RESPONSE_ERROR"} or code in {"PROVIDER_RESPONSE_ERROR", "STREAM_TRUNCATED", "EMPTY_RESPONSE"}:\n            detail = "Không thể hoàn tất phản hồi từ mô hình AI lúc này. Bạn có thể thử lại."\n        else:\n            detail = "Không thể hoàn tất phản hồi AI lúc này. Bạn có thể thử lại."\n        return f"⚠️ {detail}\\nTin nhắn của bạn đã được lưu trong lịch sử phiên."\n\n'''
if helper_method not in text:
    if method_anchor not in text:
        raise SystemExit("batch1: chat generate method anchor not found")
    text = text.replace(method_anchor, helper_method + method_anchor, 1)

legacy_expr = r'f"⚠️ Không thể hoàn tất phản hồi: {public_error.safe_message}\nTin nhắn của bạn đã được lưu trong lịch sử phiên."'
new_expr = 'self._format_public_failure(user_message, public_error)'
legacy_count = text.count(legacy_expr)
if legacy_count:
    text = text.replace(legacy_expr, new_expr)
if "Không thể hoàn tất phản hồi: {public_error.safe_message}" in text:
    raise SystemExit("batch1: legacy mixed-language public failure wrapper still present")
if text.count(new_expr) < 2:
    raise SystemExit(f"batch1: expected both chat failure returns localized, found {text.count(new_expr)}")

path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# 3) Regression expectations: machine error must stay canonical and raw
# WinError/HTTP diagnostic strings must not survive in any public field.
# ---------------------------------------------------------------------------
path = Path("tests/test_prod_vietnamese_input_tolerance_01.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '        self.assertIn("Không thể kết nối đến nhà cung cấp mô hình AI", res["content"])\n        # Backend error diagnostic must be preserved in dict\n        self.assertIn("WinError 10061", res["error"])\n',
    '        self.assertIn("Không thể hoàn tất phản hồi từ mô hình AI", res["content"])\n        # Public machine error stays canonical; raw transport detail is not exposed.\n        self.assertEqual(res["error"], "PROVIDER_RESPONSE_ERROR")\n        self.assertNotIn("WinError 10061", str(res.get("public_error", {})))\n',
    1,
)
text = text.replace(
    '        self.assertIn("Không thể kết nối đến nhà cung cấp mô hình AI", res["content"])\n        self.assertIn("WinError 10061", res["error"])\n',
    '        self.assertIn("Không thể hoàn tất phản hồi từ mô hình AI", res["content"])\n        self.assertEqual(res["error"], "PROVIDER_RESPONSE_ERROR")\n        self.assertNotIn("WinError 10061", str(res.get("public_error", {})))\n',
    1,
)
path.write_text(text, encoding="utf-8")

print("batch1 error-truth + localized chat failure patch applied")
