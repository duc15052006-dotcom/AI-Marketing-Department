"""Lightweight post-init extension hooks for zero-dependency schema models.

Hooks are infrastructure extension points only. They run after BaseModel field
validation and must raise to fail closed when a registered invariant is violated.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Callable, List


_ModelHook = Callable[[Any], None]
_LOCK = RLock()
_POST_INIT_HOOKS: List[_ModelHook] = []


def register_model_post_init_hook(hook: _ModelHook) -> None:
    """Register one process-local model post-init hook exactly once."""
    if not callable(hook):
        raise TypeError("MODEL_POST_INIT_HOOK_MUST_BE_CALLABLE")
    with _LOCK:
        if hook not in _POST_INIT_HOOKS:
            _POST_INIT_HOOKS.append(hook)


def run_model_post_init_hooks(instance: Any) -> None:
    """Run a stable snapshot of registered hooks for one initialized model."""
    with _LOCK:
        hooks = tuple(_POST_INIT_HOOKS)
    for hook in hooks:
        hook(instance)
