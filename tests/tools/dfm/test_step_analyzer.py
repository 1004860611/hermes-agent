import json
from pathlib import Path

from tools.dfm.analyzers.base import AnalyzerContext, CancellationToken
from tools.dfm.analyzers.step import StepAnalyzer
from tools.dfm.contracts import (
    EffectiveParameter,
    InputRecord,
    PlanRecord,
    WorkerEvent,
    WorkerRequest,
    WorkerResult,
)
from tools.dfm.runtime.process import ProcessResult


class SuccessfulRunner:
    def __init__(self):
        self.request = None

    def run(self, argv, cwd, timeout_seconds, cancellation, on_event):
        request_path = Path(argv[-1])
        self.request = WorkerRequest.from_dict(
            json.loads(request_path.read_text(encoding="utf-8"))
        )
        output = Path(self.request.output_dir)
        output.mkdir(parents=True, exist_ok=True)
        report = output / "dfm_report.json"
        report.write_text('{"issue_count": 0}', encoding="utf-8")
        result = WorkerResult(
            1,
            "legacy-step-v1",
            "a" * 64,
            "injection",
            "injection.legacy-baseline",
            self.request.parameters,
            "worker_result.json",
            [{"kind": "report_json", "path": report.name, "media_type": "application/json"}],
        )
        (output / result.result_path).write_text(
            json.dumps(result.to_dict()), encoding="utf-8"
        )
        on_event(WorkerEvent(1, "artifact", kind="report_json", path=report.name))
        on_event(WorkerEvent(1, "completed", path=result.result_path))
        return ProcessResult(0, "", "")


def test_step_analyzer_runs_persisted_plan_and_returns_contained_artifacts(tmp_path):
    input_path = tmp_path / "inputs" / "part.step"
    input_path.parent.mkdir()
    input_path.write_bytes(b"opaque-step")
    input_record = InputRecord(
        "input_1", "step", "part.step", "inputs/part.step", 11, "a" * 64, "now"
    )
    plan = PlanRecord(
        "plan_1",
        "step",
        ["step"],
        "ready",
        "now",
        process="injection",
        process_adapter_version="legacy-injection-v1",
        scope_id="injection.legacy-baseline",
        scope_version="1.0.0",
        input_ids=["input_1"],
        input_hashes={"input_1": "a" * 64},
        parameters={
            "min_wall_mm": EffectiveParameter(1.2, "mm", "injection_legacy_default")
        },
    )
    runner = SuccessfulRunner()
    analyzer = StepAnalyzer(runner=runner, dependency_probe=lambda: True)
    context = AnalyzerContext("dfm_1", tmp_path, "step", [input_record], "run_1", plan)

    artifacts = analyzer.run(context, CancellationToken())

    assert runner.request.process == "injection"
    assert runner.request.scope_id == "injection.legacy-baseline"
    assert {artifact.kind for artifact in artifacts} == {"report_json", "worker_result"}
    assert all((tmp_path / artifact.relative_path).is_file() for artifact in artifacts)
