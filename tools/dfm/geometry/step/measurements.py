"""Stable M1.2 measurement/evaluation normalization for legacy STEP results."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

from ...contracts import GeometryRef, MeasurementRecord


MEASUREMENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MetricSpec:
    value_key: str
    unit: str | None
    parameter_key: str
    threshold_key: str
    operator: str


_ISSUE_METRICS: dict[str, MetricSpec] = {
    "tiny_edge": MetricSpec("length_mm", "mm", "min_edge_mm", "threshold_mm", ">="),
    "small_cylindrical_feature": MetricSpec(
        "diameter_mm", "mm", "min_hole_diameter_mm", "threshold_mm", ">="
    ),
    "small_circular_edge": MetricSpec(
        "diameter_mm", "mm", "min_hole_diameter_mm", "threshold_mm", ">="
    ),
    "small_tool_radius": MetricSpec(
        "radius_mm", "mm", "min_tool_radius_mm", "threshold_mm", ">="
    ),
    "low_draft": MetricSpec(
        "draft_angle_deg", "degree", "min_draft_deg", "threshold_deg", ">="
    ),
    "narrow_machining_gap": MetricSpec(
        "distance_mm", "mm", "min_machining_gap_mm", "threshold_mm", ">="
    ),
    "thin_wall": MetricSpec("distance_mm", "mm", "min_wall_mm", "threshold_mm", ">="),
    "narrow_slot": MetricSpec(
        "distance_mm", "mm", "min_slot_width_mm", "threshold_mm", ">="
    ),
    "planar_step": MetricSpec(
        "distance_mm", "mm", "max_planar_step_mm", "threshold_mm", ">"
    ),
    "local_boss_thick": MetricSpec(
        "thickness_ratio",
        "ratio",
        "local_boss_thickness_ratio",
        "threshold_ratio",
        "<=",
    ),
    "small_face": MetricSpec(
        "area_mm2", "mm2", "min_face_area_mm2", "threshold_mm2", ">="
    ),
    "sliver_face": MetricSpec(
        "estimated_width_mm",
        "mm",
        "max_sliver_face_width_mm",
        "width_threshold_mm",
        ">=",
    ),
    "hole_edge_clearance": MetricSpec(
        "clearance_mm", "mm", "min_hole_edge_distance_mm", "threshold_mm", ">="
    ),
    "hole_web_thin": MetricSpec(
        "web_mm", "mm", "min_hole_web_mm", "threshold_mm", ">="
    ),
    "deep_hole_ratio": MetricSpec(
        "depth_diameter_ratio", "ratio", "max_hole_depth_ratio", "threshold_ratio", "<="
    ),
    "thin_wall_field": MetricSpec(
        "thickness_mm", "mm", "min_wall_mm", "threshold_mm", ">="
    ),
    "thick_section": MetricSpec(
        "thickness_mm", "mm", "max_wall_mm", "threshold_mm", "<="
    ),
    "thickness_variation": MetricSpec(
        "ratio", "ratio", "thickness_variation_ratio", "threshold_ratio", "<="
    ),
    "surface_g1_break": MetricSpec(
        "normal_angle_deg", "degree", "continuity_g1_angle_deg", "threshold_deg", "<="
    ),
    "surface_g2_jump": MetricSpec(
        "curvature_jump", "1/mm", "continuity_g2_curvature_jump", "threshold", "<="
    ),
    "undercut_negative_draft": MetricSpec(
        "signed_draft_deg",
        "degree",
        "undercut_negative_draft_deg",
        "threshold_deg",
        ">=",
    ),
    "side_action_cylinder": MetricSpec(
        "axis_pull_alignment",
        "ratio",
        "side_core_axis_pull_abs_dot_max",
        "threshold",
        ">=",
    ),
    "hole_draft_undercut": MetricSpec(
        "worst_reverse_draft_deg",
        "degree",
        "undercut_negative_draft_deg",
        "threshold_deg",
        ">=",
    ),
}


@lru_cache(maxsize=1)
def issue_catalog() -> dict[str, dict[str, Any]]:
    path = (
        Path(__file__).resolve().parents[2]
        / "scopes"
        / "injection"
        / "legacy_issue_catalog_v1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["code"]): item for item in payload["issues"]}


def normalize_legacy_measurements(
    issues: list[dict[str, Any]],
    *,
    input_sha256: str,
    algorithm_version: str,
    stats: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    process: str = "injection",
) -> list[MeasurementRecord]:
    measurements = _model_measurements(stats or {}, input_sha256, algorithm_version)
    if process == "die_casting":
        return measurements
    for issue_index, issue in enumerate(issues, start=1):
        code = str(issue.get("code") or "unknown")
        catalog_entry = issue_catalog().get(code, {})
        metric = issue.get("metric") if isinstance(issue.get("metric"), dict) else {}
        spec = _ISSUE_METRICS.get(code) or _infer_metric(metric)
        if spec is None:
            continue
        value = metric.get(spec.value_key)
        if not isinstance(value, (int, float, bool)):
            continue
        issue_id = str(issue.get("id") or f"issue-{issue_index}")
        measurement_id = f"measurement-{issue_id.lower()}"
        refs: list[GeometryRef] = []
        for ref in issue.get("refs") or []:
            if isinstance(ref, dict) and ref.get("kind") in {
                "face",
                "edge",
                "solid",
                "vertex",
            }:
                try:
                    refs.append(
                        GeometryRef(str(ref["kind"]), int(ref["index"]), input_sha256)
                    )
                except (KeyError, TypeError, ValueError):
                    continue
        expected = metric.get(spec.threshold_key)
        if expected is None:
            expected = (thresholds or {}).get(spec.parameter_key)
        measurements.append(
            MeasurementRecord(
                measurement_id,
                code,
                spec.value_key,
                value,
                spec.unit,
                "measured",
                refs,
                "legacy_step_issue_adapter",
                algorithm_version,
                input_sha256,
                diagnostics={
                    "legacy_issue_id": issue_id,
                    "check_family": catalog_entry.get("family", "unmapped"),
                    "evaluation_hint": {
                        "parameter_ref": spec.parameter_key,
                        "operator": spec.operator,
                        "fallback_expected": expected,
                    },
                },
            )
        )
    return measurements


def _model_measurements(
    stats: dict[str, Any], input_sha256: str, algorithm_version: str
) -> list[MeasurementRecord]:
    values: list[tuple[str, Any, str | None]] = []
    bbox = stats.get("bbox_size_mm")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 3:
        values.extend(
            (f"bbox_{axis}_mm", value, "mm") for axis, value in zip("xyz", bbox)
        )
    for key, unit in (("area_mm2", "mm2"), ("volume_mm3", "mm3"), ("valid_brep", None)):
        if isinstance(stats.get(key), (int, float, bool)):
            values.append((key, stats[key], unit))
    topology = stats.get("topology") if isinstance(stats.get("topology"), dict) else {}
    for key in ("solids", "shells", "faces", "edges", "vertices"):
        if isinstance(topology.get(key), int):
            values.append((f"topology_{key}", topology[key], "count"))
    return [
        MeasurementRecord(
            f"measurement-model-{index:03d}",
            "model_geometry",
            metric,
            value,
            unit,
            "measured",
            [],
            "opencascade_model_index",
            algorithm_version,
            input_sha256,
        )
        for index, (metric, value, unit) in enumerate(values, start=1)
    ]


def _infer_metric(metric: dict[str, Any]) -> MetricSpec | None:
    ignored = {"face", "edge", "face_a", "face_b", "stage_order", "render_checks"}
    for key, value in metric.items():
        if (
            key in ignored
            or key.startswith("threshold")
            or not isinstance(value, (int, float, bool))
        ):
            continue
        unit = (
            "mm" if key.endswith("_mm") else "degree" if key.endswith("_deg") else None
        )
        return MetricSpec(key, unit, "legacy_unmapped", "threshold", "unknown")
    return None
