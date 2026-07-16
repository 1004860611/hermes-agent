from pathlib import Path
import json

import pytest

from tools.dfm.contracts import EffectiveParameter, WorkerRequest
from tools.dfm.runtime.events import parse_worker_event


def _request(
    tmp_path: Path,
    *,
    process: str = "injection",
    max_evidence_findings: int | None = None,
) -> Path:
    input_path = tmp_path / "part.step"
    input_path.write_bytes(b"opaque-step")
    payload = WorkerRequest(
        schema_version=1,
        run_id="run_worker",
        input_path=str(input_path),
        output_dir=str(tmp_path / "artifacts"),
        process=process,
        scope_id="injection.legacy-baseline",
        analyzer_version="legacy-step-v1",
        parameters={
            "min_wall_mm": EffectiveParameter(
                1.2, "mm", "injection_legacy_default"
            ),
            "pull_dir": EffectiveParameter(
                [0.0, 0.0, 1.0], None, "injection_legacy_default"
            ),
        },
        max_evidence_findings=max_evidence_findings,
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(payload.to_dict()), encoding="utf-8")
    return request_path


def _events(output: str):
    return [event for line in output.splitlines() if (event := parse_worker_event(line))]


def test_worker_rejects_non_injection_before_occ_probe(tmp_path, monkeypatch, capsys):
    from tools.dfm.workers import step_worker

    monkeypatch.setattr(
        step_worker,
        "_occ_available",
        lambda: pytest.fail("OCC probe must not run for unsupported processes"),
    )

    assert step_worker.run_request(_request(tmp_path, process="machining")) == 1

    events = _events(capsys.readouterr().out)
    assert events[-1].type == "error"
    assert events[-1].code == "unsupported_capability"
    assert not (tmp_path / "artifacts" / "worker_result.json").exists()


def test_worker_reports_dependency_missing_without_result(tmp_path, monkeypatch, capsys):
    from tools.dfm.workers import step_worker

    monkeypatch.setattr(step_worker, "_occ_available", lambda: False)

    assert step_worker.run_request(_request(tmp_path)) == 1

    events = _events(capsys.readouterr().out)
    assert events[-1].type == "error"
    assert events[-1].code == "dependency_missing"
    assert not (tmp_path / "artifacts" / "worker_result.json").exists()


def test_worker_builds_legacy_config_from_effective_parameters(tmp_path):
    from tools.dfm.workers.step_worker import _legacy_config

    request_path = _request(tmp_path)
    request = WorkerRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8")))

    config = _legacy_config(request)

    assert config == {
        "process": "injection",
        "thresholds": {"min_wall_mm": 1.2, "pull_dir": [0.0, 0.0, 1.0]},
    }


def test_worker_passes_evidence_budget_to_legacy_config(tmp_path):
    from tools.dfm.workers.step_worker import _legacy_config

    request_path = _request(tmp_path, max_evidence_findings=12)
    request = WorkerRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8")))

    assert _legacy_config(request)["max_evidence_issues"] == 12
