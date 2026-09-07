"""Opt-in visual desktop CLI with operator confirmation before each action."""
import argparse
import json
import os
import sys
import time


def main():
    parser = argparse.ArgumentParser(description='Observe, propose, approve, act and re-observe one Windows window.')
    parser.add_argument('--hwnd', type=lambda s: int(s, 0), required=True)
    parser.add_argument('--goal', required=True)
    parser.add_argument('--vision-url', required=True, help='Trusted image-capable Chat Completions base URL, e.g. https://host/v1')
    parser.add_argument('--vision-model', required=True)
    parser.add_argument('--max-steps', type=int, default=10)
    args = parser.parse_args()
    if not sys.stdin.isatty(): parser.error('An interactive local terminal is required')
    if not 1 <= args.max_steps <= 50: parser.error('max-steps must be 1..50')
    from desktop.vision import CompatibleVisionPlanner, VisualLoop
    planner = CompatibleVisionPlanner(args.vision_url, args.vision_model, os.environ.get('DESKTOP_VISION_API_KEY', ''))
    print('Goal:', args.goal)
    print('Window screenshots and goal will be sent to:', args.vision_url)
    print('Every proposed action requires approval. Esc / screen corner stops.')
    if input('Type RUN to authorize this session and screenshot sharing: ').strip() != 'RUN': return 0
    print('Focus the target window within 5 seconds.')
    time.sleep(5)
    from desktop.windows import WindowsBackend
    from desktop.controller import DesktopSession
    session = DesktopSession(WindowsBackend(args.hwnd), max_actions=args.max_steps, lifetime=900)
    def approve(proposal):
        print(json.dumps(proposal, ensure_ascii=False, indent=2))
        if input('Switch to this terminal. Type YES for this exact action, anything else stops: ').strip() != 'YES':
            return False
        print('Refocus the SAME target window within 5 seconds.')
        time.sleep(5)
        return True
    result = VisualLoop(session, planner, approve, max_steps=args.max_steps).run(args.goal)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, ImportError):
        # Do not echo provider responses, tokens or clipboard contents.
        print('Visual desktop stopped. Check window, provider configuration and permissions.', file=sys.stderr)
        raise SystemExit(1)
