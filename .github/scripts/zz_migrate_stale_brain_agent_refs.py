from pathlib import Path

root = Path('.')
old = 'BrainAgentId.' + 'STRATEGIST'
new = 'BrainAgentId.CONTENT'
changed = []

for path in root.rglob('*.py'):
    if any(part in {'.git', '.venv', 'venv', 'site-packages'} for part in path.parts):
        continue
    text = path.read_text(encoding='utf-8')
    if old not in text:
        continue
    text = text.replace(old, new)
    path.write_text(text, encoding='utf-8')
    changed.append(str(path))

if not changed:
    raise SystemExit('NO_STALE_BRAIN_AGENT_REFS_FOUND')

# The canonical identity regression intentionally constructs its forbidden
# token dynamically; there must be no literal removed enum reference left.
offenders = []
for path in root.rglob('*.py'):
    if any(part in {'.git', '.venv', 'venv', 'site-packages'} for part in path.parts):
        continue
    if old in path.read_text(encoding='utf-8'):
        offenders.append(str(path))
if offenders:
    raise SystemExit('STALE_BRAIN_AGENT_REFS_REMAIN: ' + ', '.join(offenders))

print('Migrated exact stale BrainAgentId references:')
for item in changed:
    print(item)
