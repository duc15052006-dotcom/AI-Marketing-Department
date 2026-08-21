import json
import sys
import urllib.request

prompt = sys.argv[1] if len(sys.argv) > 1 else "xin chào"

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
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
