"""One-shot patch ensuring local deterministic chat does not emit MODEL_STARTED."""
from pathlib import Path

p = Path("chat/engine.py")
text = p.read_text(encoding="utf-8")
old_block = '''            emitter.emit(\n                ProgressEventType.RUN_STARTED,\n                mode=ProgressMode.GENERAL_CONVERSATION.value,\n                message="Bắt đầu xử lý tin nhắn",\n            )\n            emitter.emit(\n                ProgressEventType.MODEL_STARTED,\n                message="Gửi yêu cầu đến mô hình ngôn ngữ",\n            )\n'''
new_block = '''            emitter.emit(\n                ProgressEventType.RUN_STARTED,\n                mode=ProgressMode.GENERAL_CONVERSATION.value,\n                message="Bắt đầu xử lý tin nhắn",\n            )\n'''
if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif new_block not in text:
    raise RuntimeError("chat/engine.py: progress emitter boundary drift")

anchor = '''        # Streaming execution path\n        if text_delta_sink is not None:\n'''
replacement = '''        # Only announce model execution after deterministic-local shortcuts\n        # have been ruled out. Progress events must describe work that really\n        # happened, never work that was merely possible.\n        if emitter:\n            emitter.emit(\n                ProgressEventType.MODEL_STARTED,\n                message="Gửi yêu cầu đến mô hình ngôn ngữ",\n            )\n\n        # Streaming execution path\n        if text_delta_sink is not None:\n'''
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif replacement not in text:
    raise RuntimeError("chat/engine.py: streaming boundary drift")

p.write_text(text, encoding="utf-8")
