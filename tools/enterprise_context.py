"""Per-turn enterprise context for Hermes tools.

The enterprise API server stores short-lived caller context here before
running a turn. Tool handlers receive the same task_id and can retrieve the
credentialRef without exposing it to the model prompt.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

_lock = threading.RLock()
_contexts: Dict[str, Dict[str, Any]] = {}
_thread_context = threading.local()


def set_enterprise_context(task_id: str, context: Dict[str, Any]) -> None:
    if not task_id:
        return
    with _lock:
        _contexts[task_id] = dict(context or {})


def get_enterprise_context(task_id: Optional[str]) -> Dict[str, Any]:
    if not task_id:
        return get_current_enterprise_context()
    with _lock:
        context = dict(_contexts.get(task_id) or {})
    return context or get_current_enterprise_context()


def clear_enterprise_context(task_id: str) -> None:
    if not task_id:
        return
    with _lock:
        _contexts.pop(task_id, None)


def set_current_enterprise_context(context: Dict[str, Any]) -> Dict[str, Any]:
    previous = getattr(_thread_context, "context", None)
    _thread_context.context = dict(context or {})
    return dict(previous or {})


def get_current_enterprise_context() -> Dict[str, Any]:
    return dict(getattr(_thread_context, "context", None) or {})


def clear_current_enterprise_context(previous: Optional[Dict[str, Any]] = None) -> None:
    if previous:
        _thread_context.context = dict(previous)
    elif hasattr(_thread_context, "context"):
        delattr(_thread_context, "context")
