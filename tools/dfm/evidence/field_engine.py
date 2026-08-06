"""Turn evaluated scalar fields into precisely linked evidence images."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import operator
from pathlib import Path
from typing import Any, Callable

from ..contracts import ArtifactRecord, EvidenceRecord, GeometryRef
from ..errors import DFMError


EVIDENCE_SCHEMA_VERSION = 1
_OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class FieldEvidenceEngine:
    """Hermes-side evaluator and renderer for NX objective scalar fields."""

    version = "hermes-field-evidence-v1"

    def materialize(
        self,
        project_dir: Path,
        run_id: str,
        artifacts: list[ArtifactRecord],
        *,
        max_images: int = 12,
    ) -> list[ArtifactRecord]:
        by_kind = {item.kind: item for item in artifacts}
        measurements_artifact = by_kind.get("measurements")
        evaluations_artifact = by_kind.get("evaluations")
        if measurements_artifact is None or evaluations_artifact is None:
            return []

        measurements_payload = _read_json(project_dir, measurements_artifact)
        evaluations_payload = _read_json(project_dir, evaluations_artifact)
        input_sha256 = str(measurements_payload.get("input_sha256") or "")
        if evaluations_payload.get("run_id") != run_id:
            raise DFMError(
                "evidence_input_invalid",
                "The evaluation artifact belongs to a different run.",
            )
        measurements = {
            str(item.get("measurement_id")): item
            for item in measurements_payload.get("measurements", [])
            if isinstance(item, dict) and item.get("measurement_id")
        }
        artifact_by_id = {item.artifact_id: item for item in artifacts}
        patches: list[dict[str, Any]] = []
        for evaluation in evaluations_payload.get("evaluations", []):
            if not isinstance(evaluation, dict) or evaluation.get("outcome") != "fail":
                continue
            comparison = _OPERATORS.get(str(evaluation.get("operator") or ""))
            if comparison is None:
                raise DFMError(
                    "evidence_rule_invalid",
                    "Evidence geometry cannot apply the evaluation operator.",
                )
            linked = [
                measurements[item]
                for item in evaluation.get("measurement_ids", [])
                if item in measurements
            ]
            for measurement in linked:
                for field_ref in measurement.get("field_refs", []):
                    field_artifact = artifact_by_id.get(str(field_ref))
                    if field_artifact is None or field_artifact.kind != "scalar_field":
                        raise DFMError(
                            "evidence_field_missing",
                            "A failed measurement references a missing scalar field.",
                            {"field_ref": field_ref},
                        )
                    field = _read_json(project_dir, field_artifact)
                    self._validate_field_identity(
                        project_dir,
                        field,
                        run_id,
                        input_sha256,
                        measurement,
                        artifact_by_id,
                    )
                    patches.extend(
                        self._failed_patches(
                            evaluation,
                            measurement,
                            field_ref=str(field_ref),
                            field=field,
                            comparison=comparison,
                        )
                    )

        output_dir = project_dir / "runs" / run_id / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        geometry_path = output_dir / "evidence_geometry.json"
        geometry_path.write_text(
            json.dumps(
                {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "run_id": run_id,
                    "input_sha256": input_sha256,
                    "producer": "hermes-evidence-engine",
                    "failed_patches": patches,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        generated = [
            ArtifactRecord(
                f"artifact_{run_id}_evidence_geometry",
                "evidence_geometry",
                geometry_path.relative_to(project_dir).as_posix(),
                "application/json",
                _utc_now(),
            )
        ]

        records: list[EvidenceRecord] = []
        evaluation_by_id = {
            str(item.get("evaluation_id")): item
            for item in evaluations_payload.get("evaluations", [])
            if isinstance(item, dict)
        }
        for index, patch in enumerate(patches[: max(0, max_images)], start=1):
            scene_artifact = artifact_by_id[patch["scene_ref"]]
            scene = _read_json(project_dir, scene_artifact)
            image_id = f"artifact_{run_id}_evidence_{index}"
            image_path = output_dir / f"evidence_{index:03d}.png"
            self._render(scene, patch, image_path)
            image_artifact = ArtifactRecord(
                image_id,
                "evidence_image",
                image_path.relative_to(project_dir).as_posix(),
                "image/png",
                _utc_now(),
            )
            generated.append(image_artifact)
            evaluation = evaluation_by_id[patch["evaluation_id"]]
            records.append(
                EvidenceRecord(
                    evidence_id=f"evidence_{run_id}_{index}",
                    run_id=run_id,
                    input_sha256=input_sha256,
                    operation_id=str(evaluation.get("operation_id") or ""),
                    metric_id=str(evaluation.get("metric_id") or ""),
                    measurement_ids=[str(item) for item in patch["measurement_ids"]],
                    evaluation_ids=[patch["evaluation_id"]],
                    geometry_refs=[
                        GeometryRef.from_dict(item) for item in patch["geometry_refs"]
                    ],
                    region_refs=[str(item) for item in patch["region_refs"]],
                    artifact_ref=image_id,
                    render={
                        "mode": "local_patch",
                        "producer": "hermes-evidence-renderer",
                        "version": self.version,
                        "viewport": [1280, 720],
                        "patch_id": patch["patch_id"],
                        "scene_ref": patch["scene_ref"],
                    },
                )
            )

        records_path = output_dir / "evidence_records.json"
        records_path.write_text(
            json.dumps(
                {
                    "schema_version": EVIDENCE_SCHEMA_VERSION,
                    "run_id": run_id,
                    "input_sha256": input_sha256,
                    "producer": "hermes-evidence-renderer",
                    "records": [item.to_dict() for item in records],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        generated.append(
            ArtifactRecord(
                f"artifact_{run_id}_evidence_records",
                "evidence_records",
                records_path.relative_to(project_dir).as_posix(),
                "application/json",
                _utc_now(),
            )
        )
        return generated

    @staticmethod
    def _validate_field_identity(
        project_dir: Path,
        field: dict[str, Any],
        run_id: str,
        input_sha256: str,
        measurement: dict[str, Any],
        artifact_by_id: dict[str, ArtifactRecord],
    ) -> None:
        expected = (
            run_id,
            input_sha256,
            measurement.get("operation_id"),
            measurement.get("metric_id"),
            measurement.get("quantity_id"),
        )
        actual = (
            field.get("run_id"),
            field.get("input_sha256"),
            field.get("operation_id"),
            field.get("metric_id"),
            field.get("quantity_id"),
        )
        if actual != expected:
            raise DFMError(
                "evidence_field_invalid",
                "The scalar field does not belong to its linked measurement.",
            )
        linked_payloads: dict[str, dict[str, Any]] = {}
        for ref, kind in (
            (field.get("scene_ref"), "render_scene"),
            (field.get("topology_map_ref"), "topology_map"),
        ):
            artifact = artifact_by_id.get(str(ref))
            if artifact is None or artifact.kind != kind:
                raise DFMError(
                    "evidence_field_invalid",
                    f"The scalar field references a missing {kind} artifact.",
                )
            linked = _read_json(project_dir, artifact)
            linked_payloads[kind] = linked
            if (
                linked.get("run_id") != run_id
                or linked.get("input_sha256") != input_sha256
            ):
                raise DFMError(
                    "evidence_field_invalid",
                    f"The linked {kind} artifact belongs to another run or input.",
                )
            if kind == "topology_map" and linked.get("scene_ref") != field.get(
                "scene_ref"
            ):
                raise DFMError(
                    "evidence_field_invalid",
                    "The topology map and scalar field reference different scenes.",
                )
        scene_triangles = {
            (str(primitive.get("primitive_id")), triangle_id)
            for primitive in linked_payloads["render_scene"].get("primitives", [])
            for triangle_id, _triangle in enumerate(primitive.get("triangles", []))
        }
        mapped_triangles = {
            (str(ref.get("primitive_id")), int(ref.get("triangle_id", -1)))
            for face in linked_payloads["topology_map"].get("faces", [])
            for ref in face.get("triangle_refs", [])
        }
        field_triangles = {
            (
                str(cell.get("triangle_ref", {}).get("primitive_id")),
                int(cell.get("triangle_ref", {}).get("triangle_id", -1)),
            )
            for cell in field.get("cells", [])
        }
        if not field_triangles.issubset(scene_triangles & mapped_triangles):
            raise DFMError(
                "evidence_field_invalid",
                "Scalar field cells are not present in both the scene and topology map.",
            )

    @staticmethod
    def _failed_patches(
        evaluation: dict[str, Any],
        measurement: dict[str, Any],
        *,
        field_ref: str,
        field: dict[str, Any],
        comparison: Callable[[Any, Any], bool],
    ) -> list[dict[str, Any]]:
        expected = evaluation.get("expected")
        samples = {
            str(item.get("sample_id")): item
            for item in field.get("samples", [])
            if isinstance(item, dict) and item.get("sample_id")
        }
        failed_samples = {
            sample_id
            for sample_id, sample in samples.items()
            if not comparison(sample.get("value"), expected)
        }
        if not failed_samples:
            raise DFMError(
                "evidence_field_inconsistent",
                "A failed aggregate measurement has no failing scalar-field sample.",
                {"evaluation_id": evaluation.get("evaluation_id")},
            )
        failed_cells = [
            item
            for item in field.get("cells", [])
            if isinstance(item, dict)
            and failed_samples.intersection(str(value) for value in item.get("sample_ids", []))
        ]
        groups = _connected_cells(failed_cells)
        if not groups and failed_samples:
            groups = [[]]

        results = []
        for index, cells in enumerate(groups, start=1):
            sample_ids = sorted({
                str(sample_id)
                for cell in cells
                for sample_id in cell.get("sample_ids", [])
                if str(sample_id) in failed_samples
            })
            if not sample_ids:
                sample_ids = sorted(failed_samples)
            points = [samples[item]["point"] for item in sample_ids]
            geometry_values = [
                samples[item]["geometry_ref"] for item in sample_ids
            ] + [cell["geometry_ref"] for cell in cells]
            geometry_refs = _unique_dicts(geometry_values)
            triangles = _unique_dicts([cell["triangle_ref"] for cell in cells])
            focus = min(
                (samples[item] for item in sample_ids),
                key=lambda item: float(item.get("value", 0)),
            )["point"]
            if str(evaluation.get("operator")) in {"<=", "<"}:
                focus = max(
                    (samples[item] for item in sample_ids),
                    key=lambda item: float(item.get("value", 0)),
                )["point"]
            stable = hashlib.sha256(
                f"{evaluation.get('evaluation_id')}:{field_ref}:{index}".encode("utf-8")
            ).hexdigest()[:16]
            results.append({
                "patch_id": f"patch_{stable}",
                "evaluation_id": str(evaluation.get("evaluation_id") or ""),
                "measurement_ids": [str(measurement.get("measurement_id") or "")],
                "field_ref": field_ref,
                "scene_ref": str(field.get("scene_ref") or ""),
                "topology_map_ref": str(field.get("topology_map_ref") or ""),
                "geometry_refs": geometry_refs,
                "region_refs": sorted(str(item) for item in measurement.get("region_refs", [])),
                "sample_ids": sample_ids,
                "cell_ids": sorted(str(item.get("cell_id")) for item in cells),
                "triangle_refs": triangles,
                "focus_point": focus,
                "bounds": {
                    "minimum": [min(point[axis] for point in points) for axis in range(3)],
                    "maximum": [max(point[axis] for point in points) for axis in range(3)],
                },
            })
        return results

    @staticmethod
    def _render(scene: dict[str, Any], patch: dict[str, Any], target: Path) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError as exc:
            raise DFMError(
                "evidence_renderer_unavailable",
                "Pillow is required for Hermes field evidence rendering.",
            ) from exc

        width, height = 1280, 720
        image = Image.new("RGB", (width, height), (247, 248, 250))
        draw = ImageDraw.Draw(image)
        highlighted = {
            (str(item["primitive_id"]), int(item["triangle_id"]))
            for item in patch["triangle_refs"]
        }
        basis_u = (0.70710678, -0.70710678, 0.0)
        basis_v = (0.40824829, 0.40824829, -0.81649658)
        basis_d = (0.57735027, 0.57735027, 0.57735027)

        projected: list[tuple[float, str, int, list[tuple[float, float]]]] = []
        all_xy: list[tuple[float, float]] = []
        for primitive in scene.get("primitives", []):
            primitive_id = str(primitive.get("primitive_id") or "")
            vertices = primitive.get("vertices", [])
            for triangle_id, triangle in enumerate(primitive.get("triangles", [])):
                try:
                    points = [vertices[int(index)] for index in triangle]
                except (IndexError, TypeError, ValueError) as exc:
                    raise DFMError(
                        "render_scene_invalid",
                        "A render triangle references a missing vertex.",
                    ) from exc
                xy = [(_dot(point, basis_u), _dot(point, basis_v)) for point in points]
                depth = sum(_dot(point, basis_d) for point in points) / 3.0
                projected.append((depth, primitive_id, triangle_id, xy))
                all_xy.extend(xy)
        if not all_xy:
            raise DFMError("render_scene_invalid", "The render scene is empty.")

        focus = patch["focus_point"]
        focus_xy = (_dot(focus, basis_u), _dot(focus, basis_v))
        patch_points = [patch["bounds"][key] for key in ("minimum", "maximum")]
        patch_xy = [(_dot(point, basis_u), _dot(point, basis_v)) for point in patch_points]
        scene_span = max(
            max(value[0] for value in all_xy) - min(value[0] for value in all_xy),
            max(value[1] for value in all_xy) - min(value[1] for value in all_xy),
            1.0,
        )
        patch_span = max(
            max(value[0] for value in patch_xy) - min(value[0] for value in patch_xy),
            max(value[1] for value in patch_xy) - min(value[1] for value in patch_xy),
            scene_span * 0.08,
        )
        scale = min(width, height) * 0.62 / (patch_span * 2.5)

        def screen(point: tuple[float, float]) -> tuple[int, int]:
            return (
                round(width / 2 + (point[0] - focus_xy[0]) * scale),
                round(height / 2 - (point[1] - focus_xy[1]) * scale),
            )

        for _depth, primitive_id, triangle_id, xy in sorted(projected, reverse=True):
            polygon = [screen(point) for point in xy]
            if not _visible(polygon, width, height):
                continue
            is_failed = (primitive_id, triangle_id) in highlighted
            draw.polygon(
                polygon,
                fill=(220, 57, 57) if is_failed else (196, 202, 209),
                outline=(125, 27, 27) if is_failed else (154, 161, 169),
            )
        marker = screen(focus_xy)
        radius = 8
        draw.ellipse(
            (marker[0] - radius, marker[1] - radius, marker[0] + radius, marker[1] + radius),
            fill=(255, 255, 255),
            outline=(150, 15, 15),
            width=3,
        )
        image.save(target, format="PNG")


def _read_json(project_dir: Path, artifact: ArtifactRecord) -> dict[str, Any]:
    try:
        payload = json.loads(
            (project_dir / artifact.relative_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise DFMError(
            "evidence_artifact_invalid",
            f"The {artifact.kind} artifact is not valid JSON.",
        ) from exc
    if not isinstance(payload, dict):
        raise DFMError(
            "evidence_artifact_invalid",
            f"The {artifact.kind} artifact must be a JSON object.",
        )
    return payload


def _connected_cells(cells: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    remaining = list(cells)
    groups: list[list[dict[str, Any]]] = []
    while remaining:
        group = [remaining.pop()]
        sample_ids = set(str(item) for item in group[0].get("sample_ids", []))
        changed = True
        while changed:
            changed = False
            for cell in list(remaining):
                cell_samples = set(str(item) for item in cell.get("sample_ids", []))
                if sample_ids.intersection(cell_samples):
                    remaining.remove(cell)
                    group.append(cell)
                    sample_ids.update(cell_samples)
                    changed = True
        groups.append(group)
    return groups


def _unique_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for value in values:
        key = json.dumps(value, sort_keys=True, separators=(",", ":"))
        unique[key] = value
    return list(unique.values())


def _dot(left: list[float], right: tuple[float, float, float]) -> float:
    return sum(float(left[index]) * right[index] for index in range(3))


def _visible(points: list[tuple[int, int]], width: int, height: int) -> bool:
    return not (
        max(point[0] for point in points) < 0
        or min(point[0] for point in points) >= width
        or max(point[1] for point in points) < 0
        or min(point[1] for point in points) >= height
    )
