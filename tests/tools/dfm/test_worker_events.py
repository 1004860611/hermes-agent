import json

import pytest

from tools.dfm.contracts import WorkerEvent
from tools.dfm.errors import DFMError
from tools.dfm.runtime.events import EVENT_PREFIX, encode_worker_event, parse_worker_event


def test_worker_event_round_trip_uses_versioned_prefix():
    event = WorkerEvent(1, "progress", stage="load_geometry", percent=10)

    line = encode_worker_event(event)

    assert line.startswith(EVENT_PREFIX)
    assert parse_worker_event(line) == event


def test_non_event_output_is_ignored():
    assert parse_worker_event("ordinary diagnostic output") is None


@pytest.mark.parametrize(
    "line",
    [
        EVENT_PREFIX + "not-json",
        EVENT_PREFIX + json.dumps({"schema_version": 1, "type": "unknown"}),
    ],
)
def test_invalid_prefixed_event_is_rejected(line):
    with pytest.raises(DFMError) as exc_info:
        parse_worker_event(line)

    assert exc_info.value.code == "worker_event_invalid"
