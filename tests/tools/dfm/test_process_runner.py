from pathlib import Path
import sys
import threading

import pytest

from tools.dfm.analyzers.base import CancellationToken
from tools.dfm.errors import DFMError
from tools.dfm.runtime.process import ProcessRunner


FIXTURE = Path(__file__).parent / "fixtures" / "worker_fixture.py"


def test_process_runner_streams_events_and_keeps_stderr_separate(tmp_path):
    events = []

    result = ProcessRunner().run(
        [sys.executable, str(FIXTURE), "success"],
        tmp_path / "含 空格",
        5,
        CancellationToken(),
        events.append,
    )

    assert result.returncode == 0
    assert [event.type for event in events] == ["progress", "completed"]
    assert "ordinary worker output" in result.stdout
    assert "fixture diagnostic" in result.stderr


def test_process_runner_times_out_and_terminates_worker(tmp_path):
    with pytest.raises(DFMError) as exc_info:
        ProcessRunner().run(
            [sys.executable, str(FIXTURE), "hang"],
            tmp_path,
            0.2,
            CancellationToken(),
            lambda _event: None,
        )

    assert exc_info.value.code == "worker_timeout"


def test_process_runner_honors_cancellation(tmp_path):
    token = CancellationToken()
    timer = threading.Timer(0.2, token.cancel)
    timer.start()
    try:
        with pytest.raises(DFMError) as exc_info:
            ProcessRunner().run(
                [sys.executable, str(FIXTURE), "hang"],
                tmp_path,
                5,
                token,
                lambda _event: None,
            )
    finally:
        timer.cancel()

    assert exc_info.value.code == "run_cancelled"
