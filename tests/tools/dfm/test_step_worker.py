from pathlib import Path
import json

import pytest

from tools.dfm.contracts import EffectiveRule, PlanOperation, ResolvedArgument, WorkerRequest
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
        scope_id="injection.wall-draft",
        analyzer_version="pythonocc-objective-v1",
        rules={
            "min_wall_mm": EffectiveRule(
                1.2, "mm", "injection_scope_default"
            ),
        },
        operations=[
            PlanOperation("geometry.load", "load_geometry"),
            PlanOperation(
                "geometry.topology", "inspect_topology", ["geometry.load"]
            ),
            PlanOperation(
                "geometry.draft",
                "measure_draft",
                ["geometry.topology"],
                ["injection.geometry.draft"],
                ["draft_angle_deg"],
                ["scalar_field", "render_scene", "topology_map"],
                arguments={
                    "pull_direction": ResolvedArgument(
                        [0.0, 0.0, 1.0], "fact:pull_dir:injection_scope_default"
                    )
                },
            )
        ],
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


@pytest.mark.parametrize(
    ("filename", "artifact_id", "kind"),
    [
        ("measurements.json", "measurements", "measurements"),
        ("render_scene.json", "scene_geometry", "render_scene"),
        ("topology_map.json", "topology_geometry", "topology_map"),
        ("scalar_field_draft.json", "field_draft", "scalar_field"),
    ],
)
def test_worker_assigns_stable_neutral_artifact_ids(
    tmp_path, filename, artifact_id, kind
):
    from tools.dfm.workers.step_worker import _artifact_metadata

    artifact = tmp_path / filename
    artifact.write_text("{}", encoding="utf-8")

    metadata = _artifact_metadata(artifact, tmp_path)

    assert metadata["artifact_id"] == artifact_id
    assert metadata["kind"] == kind
    assert metadata["media_type"] == "application/json"
