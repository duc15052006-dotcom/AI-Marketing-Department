"""Repair stale runtime-evaluated typing annotations in legacy regression modules."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"POST4_ASSERTION_FAILED {path}: expected one occurrence")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "tests/test_applicationization_v1.py",
    "from pathlib import Path\n\nfrom app_api import server as app_server\n",
    "from pathlib import Path\nfrom typing import Any, Dict, Tuple\n\nfrom app_api import server as app_server\n",
)

replace_exact(
    "tests/test_prod_uiauth_01_secure_bootstrap.py",
    "from typing import Dict, Optional, Tuple\n",
    "from typing import Dict, List, Optional, Tuple\n",
)

print("FULL_DEFECT_SWEEP_V2_POST4_TYPING_IMPORTS_APPLIED")
