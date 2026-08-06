import pytest

from tools.dfm.contracts import (
    EffectiveRule,
    PlanOperation,
    PlanRecord,
    RunRecord,
    RunStatus,
    WorkerEvent,
    WorkerRequest,
    WorkerResult,
)
from tools.dfm.errors import DFMError


def test_m1_plan_and_run_round_trip_preserves_execution_snapshot():
    plan = PlanRecord(
        "plan_1",
        "step",
        ["step"],
        "ready",
        "2026-07-15T00:00:00Z",
        process="injection",
        process_adapter_version="injection-wall-draft-v1",
        scope_id="injection.wall-draft",
        scope_version="1.0.0",
        input_ids=["input_1"],
        input_hashes={"input_1": "a" * 64},
        rules={
            "min_wall_mm": EffectiveRule(
                value=1.2,
                unit="mm",
                source="injection_scope_default",
            )
        },
        operations=[PlanOperation("geometry.load", "load_geometry", [])],
    )
    run = RunRecord(
        "run_1",
        "step",
        "worker-v1",
        RunStatus.QUEUED,
        "2026-07-15T00:00:01Z",
        "2026-07-15T00:00:01Z",
        plan_id=plan.plan_id,
        plan_snapshot=plan.to_dict(),
    )

    assert PlanRecord.from_dict(plan.to_dict()) == plan
    restored = RunRecord.from_dict(run.to_dict())
    assert restored.plan_id == "plan_1"
    assert restored.plan_snapshot["scope_id"] == "injection.wall-draft"


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "type": "mystery"},
        {"schema_version": 1, "type": "progress", "percent": 101},
        {"schema_version": 2, "type": "completed", "path": "result.json"},
    ],
)
def test_worker_event_rejects_invalid_payload(payload):
    with pytest.raises(DFMError) as exc_info:
        WorkerEvent.from_dict(payload)

    assert exc_info.value.code == "worker_event_invalid"


def test_worker_request_and_result_round_trip():
    rule = EffectiveRule(1.0, "degree", "project_fact")
    request = WorkerRequest(
        schema_version=1,
        run_id="run_1",
        input_path="inputs/part.step",
        output_dir="runs/run_1/artifacts",
        process="injection",
        scope_id="injection.wall-draft",
        analyzer_version="worker-v1",
        rules={"min_draft_deg": rule},
    )
    result = WorkerResult(
        schema_version=1,
        worker_version="worker-v1",
        input_sha256="b" * 64,
        process="injection",
        scope_id="injection.wall-draft",
        rules={"min_draft_deg": rule},
        result_path="runs/run_1/artifacts/worker_result.json",
        artifacts=[{"kind": "report_json", "path": "runs/run_1/artifacts/dfm_report.json"}],
    )

    assert WorkerRequest.from_dict(request.to_dict()) == request
    assert WorkerResult.from_dict(result.to_dict()) == result
