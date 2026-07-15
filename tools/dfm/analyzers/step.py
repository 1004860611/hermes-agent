"""Production STEP analyzer backed by the isolated M1 worker."""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from typing import Callable

from ..contracts import (
    WORKER_SCHEMA_VERSION,
    ArtifactRecord,
    Capability,
    CapabilityStatus,
    WorkerEvent,
    WorkerRequest,
    WorkerResult,
)
from ..errors import DFMError
from ..runtime.process import ProcessRunner
from ..workers.step_worker import WORKER_VERSION
from .base import AnalyzerContext, CancellationToken


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_dependency_probe() -> bool:
    try:
        return importlib.util.find_spec("OCC") is not None
    except (ImportError, AttributeError, ValueError):
        return False


class StepAnalyzer:
    key = "step"
    version = WORKER_VERSION
    supported_inputs = ("step", "fusion")

    def __init__(
        self,
        *,
        runner: ProcessRunner | None = None,
        dependency_probe: Callable[[], bool] | None = None,
        python_executable: str | None = None,
        timeout_seconds: float = 900,
    ) -> None:
        self.runner = runner or ProcessRunner()
        self.dependency_probe = dependency_probe or _default_dependency_probe
        self.python_executable = python_executable or sys.executable
        self.timeout_seconds = timeout_seconds

    def capability(self, context: AnalyzerContext) -> Capability:
        if not self.dependency_probe():
            return Capability(
                self.key,
                CapabilityStatus.DEPENDENCY_MISSING,
                "pythonocc-core/OpenCascade is required by the STEP analyzer.",
                "dependency_missing",
                {
                    "dependency": "pythonocc-core",
                    "worker_version": self.version,
                },
            )
        return Capability(
            self.key,
            CapabilityStatus.AVAILABLE,
            "The isolated STEP analyzer is available.",
            details={"worker_version": self.version, "supported_processes": ["injection"]},
        )

    def run(
        self,
        context: AnalyzerContext,
        cancellation: CancellationToken,
    ) -> list[ArtifactRecord]:
        cancellation.raise_if_cancelled()
        if context.plan is None:
            raise DFMError("plan_required", "A persisted DFM execution plan is required.")
        if context.plan.process != "injection":
            raise DFMError(
                "unsupported_capability",
                f"DFM process is not supported: {context.plan.process}",
                {"supported_processes": ["injection"]},
            )
        input_record = next(
            (
                item
                for item in context.inputs
                if item.input_id in context.plan.input_ids and item.kind == "step"
            ),
            None,
        )
        if input_record is None:
            raise DFMError("input_required", "The DFM plan does not reference a STEP input.")

        run_dir = context.project_dir / "runs" / context.run_id
        output_dir = run_dir / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        request = WorkerRequest(
            schema_version=WORKER_SCHEMA_VERSION,
            run_id=context.run_id,
            input_path=str((context.project_dir / input_record.relative_path).resolve()),
            output_dir=str(output_dir.resolve()),
            process=context.plan.process,
            scope_id=context.plan.scope_id,
            analyzer_version=self.version,
            parameters=context.plan.parameters,
        )
        request_path = run_dir / "request.json"
        request_path.write_text(
            json.dumps(request.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        events: list[WorkerEvent] = []
        process_result = self.runner.run(
            [
                self.python_executable,
                "-m",
                "tools.dfm.workers.step_worker",
                "--request",
                str(request_path),
            ],
            context.project_dir,
            self.timeout_seconds,
            cancellation,
            events.append,
        )
        if process_result.returncode != 0:
            error = next((event for event in reversed(events) if event.type == "error"), None)
            raise DFMError(
                error.code if error and error.code else "analyzer_failed",
                error.message if error and error.message else "The STEP analyzer failed.",
            )
        completed = [event for event in events if event.type == "completed"]
        if len(completed) != 1 or not completed[0].path:
            raise DFMError(
                "worker_result_invalid",
                "The STEP worker did not emit exactly one completion result.",
            )
        result_path = self._contained_file(output_dir, completed[0].path)
        try:
            result = WorkerResult.from_dict(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DFMError(
                "worker_result_invalid",
                "The STEP worker result could not be loaded.",
            ) from exc
        if (
            result.schema_version != WORKER_SCHEMA_VERSION
            or result.worker_version != self.version
            or result.process != context.plan.process
            or result.scope_id != context.plan.scope_id
            or result.input_sha256 != input_record.sha256
        ):
            raise DFMError(
                "worker_result_invalid",
                "The STEP worker result does not match its persisted plan.",
            )

        raw_artifacts = [
            *result.artifacts,
            {
                "kind": "worker_result",
                "path": result.result_path,
                "media_type": "application/json",
            },
        ]
        artifacts = []
        for index, item in enumerate(raw_artifacts, start=1):
            path = self._contained_file(output_dir, str(item.get("path") or ""))
            artifacts.append(
                ArtifactRecord(
                    f"artifact_{context.run_id}_{index}",
                    str(item.get("kind") or "artifact"),
                    path.relative_to(context.project_dir).as_posix(),
                    str(item.get("media_type") or "application/octet-stream"),
                    _utc_now(),
                )
            )
        return artifacts

    @staticmethod
    def _contained_file(output_dir: Path, raw_path: str) -> Path:
        relative = Path(raw_path)
        resolved = (output_dir / relative).resolve()
        if (
            not raw_path
            or relative.is_absolute()
            or not resolved.is_relative_to(output_dir.resolve())
            or not resolved.is_file()
        ):
            raise DFMError(
                "artifact_invalid",
                "The STEP worker returned an invalid artifact path.",
                {"path": raw_path},
            )
        return resolved
