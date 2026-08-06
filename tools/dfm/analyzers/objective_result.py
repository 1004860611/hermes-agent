"""Backend-neutral validation for objective geometry result artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import ArtifactRecord, PlanOperation
from ..errors import DFMError


def validate_objective_result(
    operations: list[PlanOperation],
    project_dir: Path,
    artifacts: list[ArtifactRecord],
    *,
    run_id: str,
    input_sha256: str,
    process: str,
    scope_id: str,
    error_code: str = "objective_result_invalid",
) -> None:
    """Validate the contract shared by PythonOCC and NX geometry backends."""

    measurements = next(
        (item for item in artifacts if item.kind == "measurements"), None
    )
    if measurements is None:
        raise DFMError(error_code, "Objective result must include measurements.")
    by_id = {item.artifact_id: item for item in artifacts}
    payload = _read(project_dir, measurements, error_code)
    if (
        payload.get("schema_version") != 1
        or payload.get("producer_contract") != "measurement_only"
        or not isinstance(payload.get("measurements"), list)
        or payload.get("run_id") != run_id
        or payload.get("input_sha256") != input_sha256
        or payload.get("process") != process
        or payload.get("scope_id") != scope_id
    ):
        raise DFMError(
            error_code,
            "Measurements do not implement the objective production contract.",
        )

    task_operations = {item.operation_id: item for item in operations}
    expected = {
        (operation.operation_id, metric_id, quantity_id)
        for operation in operations
        for metric_id in operation.metric_ids
        for quantity_id in operation.required_quantities
    }
    received: set[tuple[str, str, str]] = set()
    for measurement in payload["measurements"]:
        if not isinstance(measurement, dict):
            raise DFMError(error_code, "Measurements must contain JSON objects.")
        operation_id = str(measurement.get("operation_id") or "")
        metric_id = str(measurement.get("metric_id") or "")
        quantity_id = str(measurement.get("quantity_id") or "")
        operation = task_operations.get(operation_id)
        if (
            operation is None
            or measurement.get("calculator_id") != operation.calculator_id
            or metric_id not in operation.metric_ids
            or quantity_id not in operation.required_quantities
            or measurement.get("input_sha256") != input_sha256
        ):
            raise DFMError(
                error_code,
                "Measurement does not link to its submitted task contract.",
                {"measurement_id": measurement.get("measurement_id")},
            )
        field_refs = measurement.get("field_refs")
        if not isinstance(field_refs, list) or any(
            not isinstance(ref, str)
            or ref not in by_id
            or by_id[ref].kind != "scalar_field"
            for ref in field_refs
        ):
            raise DFMError(error_code, "Measurement field_refs do not resolve.")
        if "scalar_field" in operation.required_artifacts and not field_refs:
            raise DFMError(error_code, "A field-backed measurement has no field_ref.")
        if any(
            not isinstance(ref, dict) or ref.get("input_sha256") != input_sha256
            for ref in measurement.get("geometry_refs") or []
        ):
            raise DFMError(error_code, "Measurement geometry belongs to another input.")
        received.add((operation_id, metric_id, quantity_id))
    missing = sorted(expected - received)
    if missing:
        raise DFMError(
            error_code,
            "Objective measurements are missing required metric results.",
            {"missing_operation_metrics": missing},
        )

    required_kinds = {
        kind for operation in operations for kind in operation.required_artifacts
    }
    missing_kinds = sorted(required_kinds - {item.kind for item in artifacts})
    if missing_kinds:
        raise DFMError(
            error_code,
            "Objective results are missing required geometry artifacts.",
            {"missing_artifact_kinds": missing_kinds},
        )
    linked_payloads = {
        artifact.artifact_id: _read(project_dir, artifact, error_code)
        for artifact in artifacts
        if artifact.kind in {"scalar_field", "render_scene", "topology_map"}
    }
    if any(
        item.get("schema_version") != 1
        or item.get("run_id") != run_id
        or item.get("input_sha256") != input_sha256
        for item in linked_payloads.values()
    ):
        raise DFMError(error_code, "Objective geometry belongs to another run or input.")

    for artifact in artifacts:
        if artifact.kind != "scalar_field":
            continue
        field = linked_payloads[artifact.artifact_id]
        operation = task_operations.get(str(field.get("operation_id") or ""))
        if (
            operation is None
            or field.get("metric_id") not in operation.metric_ids
            or field.get("quantity_id") not in operation.required_quantities
        ):
            raise DFMError(error_code, "Scalar field does not link to its operation.")
        scene_ref = str(field.get("scene_ref") or "")
        topology_ref = str(field.get("topology_map_ref") or "")
        if (
            scene_ref not in by_id
            or by_id[scene_ref].kind != "render_scene"
            or topology_ref not in by_id
            or by_id[topology_ref].kind != "topology_map"
            or linked_payloads.get(topology_ref, {}).get("scene_ref") != scene_ref
        ):
            raise DFMError(error_code, "Scalar field scene/topology refs are inconsistent.")
        sample_ids = {
            str(item.get("sample_id"))
            for item in field.get("samples", [])
            if isinstance(item, dict) and item.get("sample_id")
        }
        if any(
            not isinstance(cell, dict)
            or not set(str(value) for value in cell.get("sample_ids", [])).issubset(
                sample_ids
            )
            for cell in field.get("cells", [])
        ):
            raise DFMError(error_code, "Scalar field cells reference missing samples.")


def _read(
    project_dir: Path, artifact: ArtifactRecord, error_code: str
) -> dict:
    try:
        payload = json.loads(
            (project_dir / artifact.relative_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise DFMError(error_code, f"The {artifact.kind} artifact is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise DFMError(error_code, f"The {artifact.kind} artifact must be an object.")
    return payload
