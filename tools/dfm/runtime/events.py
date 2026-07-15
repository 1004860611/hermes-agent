"""Versioned JSON Lines protocol emitted by isolated DFM workers."""

from __future__ import annotations

import json

from ..contracts import WorkerEvent
from ..errors import DFMError


EVENT_PREFIX = "__HERMES_DFM_EVENT__ "


def encode_worker_event(event: WorkerEvent) -> str:
    return EVENT_PREFIX + json.dumps(
        event.to_dict(),
        ensure_ascii=True,
        separators=(",", ":"),
    )


def parse_worker_event(line: str) -> WorkerEvent | None:
    stripped = line.strip()
    if not stripped.startswith(EVENT_PREFIX):
        return None
    try:
        payload = json.loads(stripped[len(EVENT_PREFIX) :])
    except json.JSONDecodeError as exc:
        raise DFMError(
            "worker_event_invalid",
            "DFM worker emitted invalid event JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise DFMError(
            "worker_event_invalid",
            "DFM worker event payload must be an object.",
        )
    return WorkerEvent.from_dict(payload)
