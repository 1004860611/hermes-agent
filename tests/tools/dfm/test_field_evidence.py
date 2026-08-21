import json
from pathlib import Path

import pytest
from PIL import Image

from tools.dfm.contracts import (
    ArtifactRecord,
    EffectiveRule,
    GeometryRef,
    MeasurementRecord,
    PlanOperation,
    PlanRecord,
    RuleBinding,
)
from tools.dfm.errors import DFMError
from tools.dfm.evaluation import EvaluationEngine
from tools.dfm.evidence import FieldEvidenceEngine
from tools.dfm.evidence.field_engine import _adaptive_views
from tools.dfm.findings import materialize_evaluated_findings


INPUT_SHA256 = "a" * 64
MEASUREMENT_ID = "measurement_draft_min"
EVALUATION_ID = f"evaluation-{MEASUREMENT_ID}"
OPERATION_ID = "measure_draft"
METRIC_ID = "injection.geometry.draft"
RULE_ID = "injection.minimum_draft"


def test_rule_binding_evaluates_geometry_measurement_without_diagnostic_hint():
    measurement = MeasurementRecord(
        measurement_id=MEASUREMENT_ID,
        operation_id=OPERATION_ID,
        calculator_id="measure_draft",
        metric_id=METRIC_ID,
        quantity_id="draft_angle_deg",
        value=1.2,
        unit="degree",
        status="measured",
        geometry_refs=[],
        method="occt_adaptive_uv_sampling",
        algorithm_version="draft-0.1.0",
        input_sha256=INPUT_SHA256,
    )
    plan = PlanRecord(
        "plan_1",
        "step",
        ["step"],
        "ready",
        "now",
        process="injection",
        rules={
            RULE_ID: EffectiveRule(
                1.5, "degree", "approved_rule_set", "3"
            )
        },
        rule_bindings=[
            RuleBinding(
                "binding.draft",
                OPERATION_ID,
                METRIC_ID,
                "draft_angle_deg",
                RULE_ID,
                ">=",
                "minimum",
            )
        ],
        operations=[
            PlanOperation(
                OPERATION_ID,
                "measure_draft",
                metric_ids=[METRIC_ID],
                required_quantities=["draft_angle_deg"],
            )
        ],
    )

    evaluations, provenance = EvaluationEngine().evaluate([measurement], plan)

    assert evaluations[0].outcome == "fail"
    assert evaluations[0].expected == 1.5
    assert evaluations[0].rule_version == "3"
    assert provenance[evaluations[0].evaluation_id]["binding_id"] == (
        "binding.draft"
    )
    assert PlanRecord.from_dict(plan.to_dict()).rule_bindings == plan.rule_bindings


def test_failed_scalar_field_renders_precise_evidence_and_finding(tmp_path):
    artifacts = _write_pipeline_inputs(tmp_path)

    generated = FieldEvidenceEngine().materialize(
        tmp_path, "run_1", artifacts, max_images=4
    )
    all_artifacts = [*artifacts, *generated]

    image_artifacts = [item for item in generated if item.kind == "evidence_image"]
    assert len(image_artifacts) == 3
    image_artifact = image_artifacts[0]
    with Image.open(tmp_path / image_artifact.relative_path) as image:
        red_pixels = sum(
            1
            for red, green, blue in image.convert("RGB").get_flattened_data()
            if red > 180 and green < 100 and blue < 100
        )
    assert red_pixels > 500

    geometry_artifact = next(
        item for item in generated if item.kind == "evidence_geometry"
    )
    geometry = json.loads(
        (tmp_path / geometry_artifact.relative_path).read_text(encoding="utf-8")
    )
    patch = geometry["failed_patches"][0]
    assert patch["sample_ids"] == ["sample-1", "sample-2"]
    assert patch["triangle_refs"] == [
        {"primitive_id": "body-1", "triangle_id": 0}
    ]
    assert patch["geometry_refs"] == [
        {"kind": "face", "index": 17, "input_sha256": "a" * 64}
    ]
    assert patch["surface_normal"] == pytest.approx(
        [0.9998871487923587, 0, 0.015022971739553945]
    )

    records_artifact = next(
        item for item in generated if item.kind == "evidence_records"
    )
    records = json.loads(
        (tmp_path / records_artifact.relative_path).read_text(encoding="utf-8")
    )
    assert records["records"][0]["evaluation_ids"] == [
        EVALUATION_ID
    ]
    assert records["records"][0]["artifact_ref"] == image_artifact.artifact_id
    assert [item["render"]["view_id"] for item in records["records"]] == [
        "pull",
        "surface",
        "side",
    ]
    directions = [item["render"]["camera_direction"] for item in records["records"]]
    assert abs(directions[0][2]) == pytest.approx(1)
    assert all(
        abs(sum(left[i] * right[i] for i in range(3))) < 0.999
        for index, left in enumerate(directions)
        for right in directions[index + 1 :]
    )

    jsonschema = pytest.importorskip("jsonschema")
    schema_root = Path(__file__).resolve().parents[3] / "tools" / "dfm" / "schemas"
    for payload, schema_name in (
        (geometry, "evidence_geometry.schema.json"),
        (records, "evidence_record.schema.json"),
    ):
        schema = json.loads((schema_root / schema_name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(payload)

    finding = materialize_evaluated_findings(tmp_path, all_artifacts)[0]
    assert finding.evidence_refs == [
        item["evidence_id"] for item in records["records"]
    ]
    assert finding.measurement_ids == [MEASUREMENT_ID]


def test_field_evidence_rejects_cross_run_scene(tmp_path):
    artifacts = _write_pipeline_inputs(tmp_path)
    scene_artifact = next(item for item in artifacts if item.kind == "render_scene")
    scene_path = tmp_path / scene_artifact.relative_path
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    scene["run_id"] = "run_other"
    scene_path.write_text(json.dumps(scene), encoding="utf-8")

    with pytest.raises(DFMError) as exc_info:
        FieldEvidenceEngine().materialize(tmp_path, "run_1", artifacts)

    assert exc_info.value.code == "evidence_field_invalid"


@pytest.mark.parametrize(
    ("pull_direction", "surface_normal"),
    [
        ([1, 2, 3], [-2, 1, 0.5]),
        ([0, 0, 1], [0, 0, 1]),
    ],
)
def test_adaptive_views_stay_distinct_for_rotated_and_parallel_geometry(
    pull_direction, surface_normal
):
    scene = {
        "primitives": [{
            "vertices": [[-4, -2, -1], [4, -2, -1], [4, 2, 1], [-4, 2, 1]],
            "triangles": [[0, 1, 2], [0, 2, 3]],
        }]
    }
    patch = {
        "focus_point": [3, 1, 0.5],
        "surface_normal": surface_normal,
    }

    views = _adaptive_views(scene, patch, pull_direction)

    assert [item["id"] for item in views] == ["pull", "surface", "side"]
    directions = [item["basis_d"] for item in views]
    assert all(
        abs(sum(left[i] * right[i] for i in range(3))) < 0.999
        for index, left in enumerate(directions)
        for right in directions[index + 1 :]
    )
    for view in views:
        assert sum(item * item for item in view["basis_u"]) == pytest.approx(1)
        assert sum(item * item for item in view["basis_v"]) == pytest.approx(1)
        assert sum(item * item for item in view["basis_d"]) == pytest.approx(1)


def _write_pipeline_inputs(tmp_path: Path) -> list[ArtifactRecord]:
    payloads = {
        "field_draft": ("scalar_field", "scalar_field.json", {
            "schema_version": 1,
            "field_id": "field_draft",
            "run_id": "run_1",
            "input_sha256": INPUT_SHA256,
            "operation_id": OPERATION_ID,
            "metric_id": METRIC_ID,
            "quantity_id": "draft_angle_deg",
            "unit": "degree",
            "scene_ref": "scene_part",
            "topology_map_ref": "topology_part",
            "interpolation": "linear_on_triangle",
            "calculation_context": {"pull_direction": [0, 0, 1]},
            "samples": [
                {
                    "sample_id": "sample-1",
                    "point": [0, 0, 0],
                    "uv": [0, 0],
                    "surface_normal": [0.999, 0, 0.01],
                    "value": 0.6,
                    "geometry_ref": {
                        "kind": "face", "index": 17, "input_sha256": INPUT_SHA256
                    },
                    "mesh_vertex_ref": {"primitive_id": "body-1", "vertex_id": 0},
                },
                {
                    "sample_id": "sample-2",
                    "point": [10, 0, 0],
                    "uv": [1, 0],
                    "surface_normal": [0.998, 0, 0.02],
                    "value": 1.2,
                    "geometry_ref": {
                        "kind": "face", "index": 17, "input_sha256": INPUT_SHA256
                    },
                    "mesh_vertex_ref": {"primitive_id": "body-1", "vertex_id": 1},
                },
                {
                    "sample_id": "sample-3",
                    "point": [10, 10, 1],
                    "uv": [1, 1],
                    "surface_normal": [0.99, 0, 0.1],
                    "value": 1.8,
                    "geometry_ref": {
                        "kind": "face", "index": 17, "input_sha256": INPUT_SHA256
                    },
                    "mesh_vertex_ref": {"primitive_id": "body-1", "vertex_id": 2},
                },
            ],
            "cells": [{
                "cell_id": "cell-1",
                "sample_ids": ["sample-1", "sample-2", "sample-3"],
                "geometry_ref": {
                    "kind": "face", "index": 17, "input_sha256": INPUT_SHA256
                },
                "triangle_ref": {"primitive_id": "body-1", "triangle_id": 0},
            }],
            "quality": {
                "max_chordal_deviation_mm": 0.05,
                "includes_controlling_extrema": True,
            },
        }),
        "scene_part": ("render_scene", "render_scene.json", {
            "schema_version": 1,
            "scene_id": "scene_part",
            "run_id": "run_1",
            "input_sha256": INPUT_SHA256,
            "coordinate_system": "model",
            "unit": "mm",
            "primitives": [{
                "primitive_id": "body-1",
                "vertices": [[0, 0, 0], [10, 0, 0], [10, 10, 1], [0, 10, 2]],
                "triangles": [[0, 1, 2], [0, 2, 3]],
            }],
        }),
        "topology_part": ("topology_map", "topology.json", {
            "schema_version": 1,
            "map_id": "topology_part",
            "run_id": "run_1",
            "input_sha256": INPUT_SHA256,
            "scene_ref": "scene_part",
            "faces": [{
                "geometry_ref": {
                    "kind": "face", "index": 17, "input_sha256": INPUT_SHA256
                },
                "triangle_refs": [
                    {"primitive_id": "body-1", "triangle_id": 0},
                    {"primitive_id": "body-1", "triangle_id": 1},
                ],
            }],
        }),
    }
    artifacts = []
    for artifact_id, (kind, filename, payload) in payloads.items():
        target = tmp_path / filename
        target.write_text(json.dumps(payload), encoding="utf-8")
        artifacts.append(
            ArtifactRecord(artifact_id, kind, target.name, "application/json", "now")
        )

    measurements = tmp_path / "measurements.json"
    measurements.write_text(
        json.dumps({
            "schema_version": 1,
            "run_id": "run_1",
            "input_sha256": INPUT_SHA256,
            "process": "injection",
            "scope_id": "injection.geometry-core",
            "producer_contract": "measurement_only",
            "measurements": [{
                "measurement_id": MEASUREMENT_ID,
                "operation_id": OPERATION_ID,
                "calculator_id": "measure_draft",
                "metric_id": METRIC_ID,
                "quantity_id": "draft_angle_deg",
                "value": 1.2,
                "unit": "degree",
                "status": "measured",
                "geometry_refs": [],
                "region_refs": ["region.sidewall"],
                "field_refs": ["field_draft"],
                "method": "occt_adaptive_uv_sampling",
                "algorithm_version": "draft-0.1.0",
                "input_sha256": INPUT_SHA256,
                "quality": {},
                "diagnostics": {},
            }],
        }),
        encoding="utf-8",
    )
    artifacts.append(
        ArtifactRecord(
            "measurements", "measurements", measurements.name, "application/json", "now"
        )
    )
    evaluations = tmp_path / "evaluations.json"
    evaluations.write_text(
        json.dumps({
            "schema_version": 1,
            "run_id": "run_1",
            "input_sha256": INPUT_SHA256,
            "evaluations": [{
                "evaluation_id": EVALUATION_ID,
                "operation_id": OPERATION_ID,
                "metric_id": METRIC_ID,
                "measurement_ids": [MEASUREMENT_ID],
                "rule_id": RULE_ID,
                "rule_version": "3",
                "rule_hash": "c" * 64,
                "operator": ">=",
                "expected": 1.5,
                "actual": 1.2,
                "outcome": "fail"
            }]
        }),
        encoding="utf-8",
    )
    artifacts.append(
        ArtifactRecord(
            "evaluations", "evaluations", evaluations.name, "application/json", "now"
        )
    )
    return artifacts
