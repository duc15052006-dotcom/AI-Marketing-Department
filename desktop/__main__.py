"""Local operator CLI: python -m desktop --help. Never exposed over HTTP."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description='Supervised Windows desktop control (Esc / screen corner stops).')
    parser.add_argument('--hwnd', type=lambda s: int(s, 0), required=True, help='Target window handle; decimal or 0xHEX')
    parser.add_argument('--plan', type=Path, help='Local JSON list of click/type/press/scroll actions')
    parser.add_argument('--execute', action='store_true', help='Ask for local confirmation, then execute the displayed plan')
    parser.add_argument('--observe', type=Path, help='Save one approved window screenshot as PNG instead')
    args = parser.parse_args()
    if bool(args.plan) == bool(args.observe):
        parser.error('Choose exactly one of --plan or --observe')
    if args.plan:
        if args.plan.stat().st_size > 128_000:
            parser.error('Plan exceeds 128 KB')
        actions = json.loads(args.plan.read_text(encoding='utf-8'))
        if not isinstance(actions, list) or not 1 <= len(actions) <= 20 or any(not isinstance(a, dict) for a in actions):
            parser.error('Plan must be a list of 1..20 action objects')
        print(json.dumps(actions, ensure_ascii=False, indent=2))
        if not args.execute:
            print('Preview only. Add --execute to request local execution.')
            return 0
    if not sys.stdin.isatty():
        parser.error('Live use requires an interactive local terminal')
    print('Only proceed for a window you own or are authorized to operate. Input can publish or submit forms.')
    if input('Type RUN to approve this exact plan/screenshot: ').strip() != 'RUN':
        print('Cancelled.')
        return 0
    print('Focus the target window now; starting in 5 seconds. Release modifier keys. Esc stops.')
    time.sleep(5)
    from desktop.controller import DesktopSession
    from desktop.windows import WindowsBackend
    session = DesktopSession(WindowsBackend(args.hwnd))
    try:
        if args.observe:
            import base64
            result = session.observe()
            # Refuse overwrite; screenshot stays local at the operator's path.
            with args.observe.open('xb') as output:
                output.write(base64.b64decode(result['png_base64']))
            print('Saved window screenshot:', args.observe)
        else:
            for index, action in enumerate(actions):
                result = session.observe()
                dispatched = session.act({**action, 'observation_id': result['observation_id']})
                print(json.dumps({'step': index + 1, 'input_dispatched': dispatched['input_dispatched'],
                                  'semantic_success': dispatched['semantic_success']}))
                # Refresh observations, never replay an old screen or retry input.
    finally:
        session.stop()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print('Desktop stopped:', str(exc), file=sys.stderr)
        raise SystemExit(1)
