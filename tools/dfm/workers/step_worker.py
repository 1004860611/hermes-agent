"""Isolated worker wrapper for the migrated legacy STEP analyzer."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
from typing import Any

from ..contracts import WORKER_SCHEMA_VERSION, WorkerEvent, WorkerRequest, WorkerResult
from ..errors import DFMError
from ..runtime.events import encode_worker_event
from ..geometry.step.measurements import (
    MEASUREMENT_SCHEMA_VERSION,
    normalize_legacy_measurements,
)
from ..geometry.step.pipeline import validate_operations


WORKER_VERSION = "step-m12-v1"


def _emit(event_type: str, **values: Any) -> None:
    print(
        encode_worker_event(
            WorkerEvent(
                schema_version=WORKER_SCHEMA_VERSION,
                type=event_type,
                **values,
            )
        ),
        flush=True,
    )


def _occ_available() -> bool:
    try:
        return importlib.util.find_spec("OCC") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _pptx_available() -> bool:
    from ..reporting.pptx import pptx_available

    return pptx_available()


def _legacy_config(request: WorkerRequest) -> dict[str, Any]:
    config = {
        # The migrated analyzer knows only its historical generic/injection/
        # machining labels. The persisted Run keeps the real process; generic
        # is only the geometry-execution compatibility mode for die casting.
        "process": "injection" if request.process == "injection" else "generic",
        "thresholds": {
            key: parameter.value for key, parameter in request.parameters.items()
        },
    }
    if request.max_evidence_findings is not None:
        config["max_evidence_issues"] = request.max_evidence_findings
    return config


def _load_request(path: Path) -> WorkerRequest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = WorkerRequest.from_dict(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise DFMError(
            "worker_request_invalid",
            "The STEP worker request could not be loaded.",
        ) from exc
    if request.schema_version != WORKER_SCHEMA_VERSION:
        raise DFMError(
            "worker_request_invalid",
            "The STEP worker request schema version is unsupported.",
            {"schema_version": request.schema_version},
        )
    return request


def _artifact_metadata(path: Path, output_dir: Path) -> dict[str, str]:
    suffix = path.suffix.lower()
    if path.name == "measurements.json":
        kind, media_type = "measurements", "application/json"
    elif path.name == "dfm_report.json":
        kind, media_type = "report_json", "application/json"
    elif path.name == "dfm_report.md":
        kind, media_type = "report_markdown", "text/markdown"
    elif path.name == "dfm_report.pptx":
        kind = "report_presentation"
        media_type = (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
    elif suffix in {".step", ".stp"}:
        kind, media_type = "highlighted_step", "model/step"
    elif suffix == ".png":
        kind, media_type = "evidence_image", "image/png"
    else:
        kind, media_type = "diagnostic", "application/octet-stream"
    return {
        "kind": kind,
        "path": path.relative_to(output_dir).as_posix(),
        "media_type": media_type,
    }


def _input_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _execute(request: WorkerRequest) -> WorkerResult:
    if request.process not in {"injection", "die_casting"}:
        raise DFMError(
            "unsupported_capability",
            f"DFM process is not supported: {request.process}",
            {
                "requested_process": request.process,
                "supported_processes": ["die_casting", "injection"],
            },
        )
    if not _occ_available():
        raise DFMError(
            "dependency_missing",
            "pythonocc-core/OpenCascade is required by the STEP worker.",
            {"dependency": "pythonocc-core"},
        )
    if not _pptx_available():
        raise DFMError(
            "dependency_missing",
            "python-pptx is required to generate the DFM PowerPoint report.",
            {"dependency": "python-pptx", "install_extra": "hermes-agent[dfm]"},
        )

    operations = validate_operations(request.operations)

    input_path = Path(request.input_path).expanduser().resolve()
    output_dir = Path(request.output_dir).expanduser().resolve()
    if not input_path.is_file() or input_path.suffix.lower() not in {".step", ".stp"}:
        raise DFMError(
            "worker_request_invalid",
            "The STEP worker input must be an existing STEP/STP file.",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_path = output_dir / ".legacy_profile.json"
    profile_path.write_text(
        json.dumps(_legacy_config(request), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    from ..geometry.step import legacy_analyzer

    def bridge_legacy_event(event: str, **payload: Any) -> None:
        if event == "progress":
            _emit(
                "progress",
                stage=str(payload.get("stage") or "legacy_analysis"),
                percent=int(payload.get("percent") or 0),
            )
            return
        if event != "artifact":
            return
        raw_path = Path(str(payload.get("path") or ""))
        try:
            relative = raw_path.resolve().relative_to(output_dir).as_posix()
        except (OSError, ValueError):
            return
        _emit("artifact", kind=str(payload.get("type") or "artifact"), path=relative)

    legacy_analyzer.emit_dfm_event = bridge_legacy_event
    _emit("progress", stage="legacy_analysis", percent=5)
    legacy_argv = [
        str(input_path),
        "--out",
        str(output_dir),
        "--config",
        str(profile_path),
        "--process",
        "injection" if request.process == "injection" else "generic",
        "--highlight-step-name",
        "dfm_highlighted.step",
    ]
    for operation in operations:
        legacy_argv.extend(["--operation", operation])
    returncode = legacy_analyzer.main(legacy_argv)
    if returncode != 0:
        raise DFMError(
            "analyzer_failed",
            "The legacy STEP analyzer exited unsuccessfully.",
            {"returncode": returncode},
        )

    report_path = output_dir / "dfm_report.json"
    try:
        report_result = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise DFMError(
            "report_generation_failed",
            "The DFM JSON report could not be loaded for PowerPoint generation.",
        ) from exc
    if not isinstance(report_result, dict):
        raise DFMError(
            "report_generation_failed",
            "The DFM JSON report must contain an object.",
        )

    input_sha256 = _input_sha256(input_path)
    measurements = normalize_legacy_measurements(
        list(report_result.get("issues") or []),
        input_sha256=input_sha256,
        algorithm_version=WORKER_VERSION,
        stats=report_result.get("stats")
        if isinstance(report_result.get("stats"), dict)
        else {},
        thresholds=report_result.get("thresholds")
        if isinstance(report_result.get("thresholds"), dict)
        else {},
        process=request.process,
    )
    measurement_path = output_dir / "measurements.json"
    measurement_path.write_text(
        json.dumps(
            {
                "schema_version": MEASUREMENT_SCHEMA_VERSION,
                "run_id": request.run_id,
                "input_sha256": input_sha256,
                "algorithm_version": WORKER_VERSION,
                "process": request.process,
                "scope_id": request.scope_id,
                "operations": operations,
                "parameters": {
                    key: value.to_dict() for key, value in request.parameters.items()
                },
                "measurements": [item.to_dict() for item in measurements],
                "producer_contract": "measurement_only",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _emit("artifact", kind="measurements", path=measurement_path.name)

    from ..reporting import render_default_reports

    _emit("progress", stage="render_presentation", percent=97)
    for report in render_default_reports(
        artifact_dir=output_dir,
        result=report_result,
        process=request.process,
        scope_id=request.scope_id,
    ):
        _emit(
            "artifact",
            kind=report.kind,
            path=report.path.relative_to(output_dir).as_posix(),
        )

    artifacts = [
        _artifact_metadata(path, output_dir)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name not in {profile_path.name, "worker_result.json"}
    ]
    result = WorkerResult(
        schema_version=WORKER_SCHEMA_VERSION,
        worker_version=WORKER_VERSION,
        input_sha256=input_sha256,
        process=request.process,
        scope_id=request.scope_id,
        parameters=request.parameters,
        result_path="worker_result.json",
        measurement_path=measurement_path.name,
        artifacts=artifacts,
    )
    result_path = output_dir / result.result_path
    result_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for artifact in artifacts:
        _emit("artifact", kind=artifact["kind"], path=artifact["path"])
    _emit("artifact", kind="worker_result", path=result.result_path)
    _emit("progress", stage="complete", percent=100)
    _emit("completed", path=result.result_path)
    return result


def run_request(request_path: Path) -> int:
    try:
        _execute(_load_request(Path(request_path)))
    except DFMError as exc:
        _emit("error", code=exc.code, message=exc.message)
        return 1
    except Exception:
        traceback.print_exc(file=sys.stderr)
        _emit(
            "error",
            code="worker_failed",
            message="The STEP worker failed unexpectedly. Run diagnostics for details.",
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run an isolated Hermes STEP DFM worker."
    )
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    return run_request(args.request)


if __name__ == "__main__":
    raise SystemExit(main())
