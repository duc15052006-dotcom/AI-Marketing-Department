"""One-shot regression alignment for hardened chat routing contracts."""
from pathlib import Path

p = Path("tests/test_prod_core_authority_01b.py")
text = p.read_text(encoding="utf-8")
old = '''        session_b = ChatSession(chat_id="CHAT-B-001")\n        engine.generate_chat_response(session=session_b, user_message="Hello", attachments=None)\n\n        all_b = " ".join(m.content for m in captured[1].messages)\n        self.assertNotIn("Secret A data", all_b)\n'''
new = '''        session_b = ChatSession(chat_id="CHAT-B-001")\n        # Use a non-shortcut query so this trust-boundary test exercises a\n        # second real model request. "Hello" is intentionally handled by the\n        # deterministic local chat shortcut and therefore would not call the\n        # model at all.\n        engine.generate_chat_response(\n            session=session_b,\n            user_message="Explain campaign measurement tradeoffs",\n            attachments=None,\n        )\n\n        self.assertEqual(len(captured), 2)\n        all_b = " ".join(m.content for m in captured[1].messages)\n        self.assertNotIn("Secret A data", all_b)\n'''
if old in text:
    text = text.replace(old, new, 1)
elif new not in text:
    raise RuntimeError("tests/test_prod_core_authority_01b.py: cross-scope boundary drift")
p.write_text(text, encoding="utf-8")
