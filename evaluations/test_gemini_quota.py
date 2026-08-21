import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from integrations.models.gemini_adapter import GeminiProviderAdapter
from integrations.models.base import ModelMessage, ModelRequest, ModelRole

adapter = GeminiProviderAdapter(default_model="gemini-flash-latest")
import json
import urllib.request
import os

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
req = urllib.request.Request(url)
for model in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
    req = ModelRequest(
        model_name=model,
        messages=[ModelMessage(role=ModelRole.USER, content="Reply with one word: 'READY'")],
        temperature=0.1,
        max_tokens=10,
    )
    resp = adapter.generate(req)
    print(f"Model {model} -> Status: {resp.status}, Content: {resp.content}, Error: {resp.error}")
