"""Isolated PythonOCC demo backend for neutral DFM objective fields."""

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
from ..geometry.step.field_export import (
    SCENE_ARTIFACT_ID,
    TOPOLOGY_ARTIFACT_ID,
    export_objective_fields,
)
from ..geometry.step.pipeline import validate_operations


WORKER_VERSION = "pythonocc-objective-v1"


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
        artifact_id, kind, media_type = "measurements", "measurements", "application/json"
    elif path.name == "render_scene.json":
        artifact_id, kind, media_type = SCENE_ARTIFACT_ID, "render_scene", "application/json"
    elif path.name == "topology_map.json":
        artifact_id, kind, media_type = TOPOLOGY_ARTIFACT_ID, "topology_map", "application/json"
    elif path.name.startswith("scalar_field_") and suffix == ".json":
        artifact_id, kind, media_type = path.stem.removeprefix("scalar_"), "scalar_field", "application/json"
    else:
        artifact_id, kind, media_type = path.stem, "diagnostic", "application/octet-stream"
    return {
        "artifact_id": artifact_id,
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
    validate_operations(request.operations)

    input_path = Path(request.input_path).expanduser().resolve()
    output_dir = Path(request.output_dir).expanduser().resolve()
    if not input_path.is_file() or input_path.suffix.lower() not in {".step", ".stp"}:
        raise DFMError(
            "worker_request_invalid",
            "The STEP worker input must be an existing STEP/STP file.",
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    input_sha256 = _input_sha256(input_path)
    _emit("progress", stage="objective_geometry", percent=10)
    exported = export_objective_fields(
        input_path,
        run_id=request.run_id,
        input_sha256=input_sha256,
        operations=request.operations,
    )
    _emit("progress", stage="write_objective_artifacts", percent=85)
    measurement_path = output_dir / "measurements.json"
    measurement_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": request.run_id,
                "input_sha256": input_sha256,
                "process": request.process,
                "scope_id": request.scope_id,
                "measurements": [
                    item.to_dict() for item in exported["measurements"]
                ],
                "producer_contract": "measurement_only",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (output_dir / "render_scene.json").write_text(
        json.dumps(exported["scene"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "topology_map.json").write_text(
        json.dumps(exported["topology"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for field_id, field in exported["fields"]:
        (output_dir / f"scalar_{field_id}.json").write_text(
            json.dumps(field, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    artifacts = [
        _artifact_metadata(path, output_dir)
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name != "worker_result.json"
    ]
    result = WorkerResult(
        schema_version=WORKER_SCHEMA_VERSION,
        worker_version=WORKER_VERSION,
        input_sha256=input_sha256,
        process=request.process,
        scope_id=request.scope_id,
        rules=request.rules,
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
