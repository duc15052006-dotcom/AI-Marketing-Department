"""Manual local live-chat smoke client.

This module is intentionally inert when imported so test discovery cannot make
network requests or terminate the Python process. Run it explicitly as a
script when a local backend is already listening on 127.0.0.1:8765.
"""
from __future__ import annotations

import json
import sys
import urllib.request


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prompt = args[0] if args else "xin chào"

    url = "http://127.0.0.1:8765/api/chat/sessions/first_turn"
    payload = json.dumps({"content": prompt, "auto_execute": True}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"HTTP_STATUS: {resp.status}")
            print(f"ROUTE: {data.get('route')}")
            print(f"FIVE_AGENT_CALL_COUNT: {data.get('five_agent_call_count')}")
            msg = data.get("message", {})
            print(f"MESSAGE_STATUS: {msg.get('status')}")
            content = msg.get("content", "")
            print(f"CONTENT_PREVIEW: {content[:150]}")
            return 0
    except Exception as exc:
        # Keep developer smoke output useful without reflecting raw URLs,
        # headers, paths, or response bodies from arbitrary exceptions.
        print(f"ERROR_TYPE: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
