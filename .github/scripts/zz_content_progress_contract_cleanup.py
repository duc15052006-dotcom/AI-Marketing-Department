from pathlib import Path


def replace_exact(text: str, old: str, new: str, *, path: str, expected: int) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"EXPECTED_PATTERN_COUNT {path}: expected {expected}, found {count}: {old!r}")
    return text.replace(old, new)


stream_path = Path("tests/test_prod_python_streaming_endpoint_01.py")
stream = stream_path.read_text(encoding="utf-8")
stream = replace_exact(
    stream,
    '"STRATEGIST"',
    '"CONTENT"',
    path=str(stream_path),
    expected=2,
)
stream_path.write_text(stream, encoding="utf-8")

progress_path = Path("tests/test_prod_runtime_progress_01.py")
progress = progress_path.read_text(encoding="utf-8")
# This is a current production progress contract suite, not a legacy migration suite.
# Every Strategist spelling here is stale canonical-role vocabulary.
progress = replace_exact(progress, "STRATEGIST", "CONTENT", path=str(progress_path), expected=6)
progress = replace_exact(progress, "strategist", "content", path=str(progress_path), expected=1)
progress = replace_exact(progress, "Strategist", "Content", path=str(progress_path), expected=2)
progress_path.write_text(progress, encoding="utf-8")

print("Migrated stale production progress/streaming expectations to canonical Content.")
