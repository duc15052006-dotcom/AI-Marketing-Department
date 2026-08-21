import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.base import ModelMessage, ModelRequest, ModelRole

adapter = GeminiProviderAdapter(default_model="gemini-flash-latest")
req = ModelRequest(
    model_name="gemini-flash-latest",
    messages=[ModelMessage(role=ModelRole.USER, content="Reply with one word: 'AVAILABLE'")],
    temperature=0.1,
    max_tokens=10,
)
import time

print("Waiting 20s to test if 429 was per-minute quota or daily limit...")
time.sleep(20.0)

resp = adapter.generate(req)
print("gemini-flash-latest Availability Status (Attempt 2):", resp.status)
print("gemini-flash-latest Content:", resp.content)
print("gemini-flash-latest Error:", resp.error)
print("gemini-flash-latest Usage:", resp.usage)
