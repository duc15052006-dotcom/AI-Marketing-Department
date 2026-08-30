"""Manual live chat probe.

This file intentionally keeps its historical name, but importing it must be
side-effect free so automated test discovery can never perform network I/O or
terminate the pytest process.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from typing import Sequence


DEFAULT_URL = "http://127.0.0.1:8765/api/chat/sessions/first_turn"


def run_probe(prompt: str, *, url: str = DEFAULT_URL, timeout: float = 30.0) -> int:
    payload = json.dumps({"content": prompt, "auto_execute": True}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        # Manual diagnostics must not dump raw exception strings because they
        # can include URLs, local paths, provider payloads, or other details.
        print(f"ERROR_TYPE: {type(exc).__name__}")
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    prompt = args[0] if args else "xin chào"
    return run_probe(prompt)


if __name__ == "__main__":
    raise SystemExit(main())
