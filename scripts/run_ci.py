"""Hermetic repository test entrypoint used by CI and fresh-start acceptance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    env = os.environ.copy()
    env["RUN_LIVE_PROVIDER_TESTS"] = "0"
    env["RUN_REAL_MODEL_TEST"] = "0"
    env["RUN_LIVE_MODEL_TESTS"] = "0"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Existing unit tests historically expect a fresh in-memory LocalKnowledgeRepository.
    # Durable behavior has its own adversarial regression and fresh-start guard.
    env["AI_MARKETING_KNOWLEDGE_EPHEMERAL"] = "1"

    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
        "-v",
    ]
    completed = subprocess.run(command, cwd=REPO_ROOT, env=env, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
