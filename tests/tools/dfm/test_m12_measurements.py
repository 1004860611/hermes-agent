import ast
import json
from pathlib import Path

import pytest

from tools.dfm.contracts import (
    EvaluationRecord,
    GeometryRef,
    MeasurementRecord,
    EffectiveParameter,
    PlanRecord,
    PlanOperation,
)
from tools.dfm.errors import DFMError
from tools.dfm.evaluation import EvaluationEngine
from tools.dfm.geometry.step.measurements import (
    _ISSUE_METRICS,
    issue_catalog,
    normalize_legacy_measurements,
)
from tools.dfm.geometry.step.pipeline import validate_operations
from tools.dfm.workers.step_worker import WORKER_VERSION
from tests.tools.dfm.baseline import occ_available


def test_measurement_and_evaluation_contracts_round_trip():
    measurement = MeasurementRecord(
        "measurement-dfm-001",
        "thin_wall",
        "distance_mm",
        0.8,
        "mm",
        "measured",
        [GeometryRef("face", 3, "a" * 64)],
        "legacy_step_issue_adapter",
        "legacy-step-v1",
        "a" * 64,
    )
    evaluation = EvaluationRecord(
        "evaluation-dfm-001",
        "thin_wall",
        [measurement.measurement_id],
        "min_wall_mm",
        ">=",
        1.2,
        0.8,
        "fail",
    )

    assert MeasurementRecord.from_dict(measurement.to_dict()) == measurement
    assert EvaluationRecord.from_dict(evaluation.to_dict()) == evaluation


def test_legacy_issue_normalization_separates_measurement_and_threshold():
    measurements = normalize_legacy_measurements(
        [
            {
                "id": "DFM-001",
                "code": "thin_wall",
                "metric": {"distance_mm": 0.8, "threshold_mm": 1.2},
                "refs": [{"kind": "face", "index": 2}, {"kind": "face", "index": 5}],
            }
        ],
        input_sha256="b" * 64,
        algorithm_version="legacy-step-v1",
    )

    assert measurements[0].value == 0.8
    assert measurements[0].diagnostics == {
        "legacy_issue_id": "DFM-001",
        "check_family": "planar_spacing",
        "evaluation_hint": {
            "parameter_ref": "min_wall_mm",
            "operator": ">=",
            "fallback_expected": 1.2,
        },
    }
    assert [ref.index for ref in measurements[0].geometry_refs] == [2, 5]
    plan = PlanRecord(
        "plan_1",
        "step",
        ["step"],
        "ready",
        "now",
        process="injection",
        parameters={
            "min_wall_mm": EffectiveParameter(
                1.2, "mm", "injection_legacy_default"
            )
        },
    )
    evaluations, provenance = EvaluationEngine().evaluate(measurements, plan)
    assert evaluations[0].expected == 1.2
    assert evaluations[0].parameter_ref == "min_wall_mm"
    assert evaluations[0].measurement_refs == [measurements[0].measurement_id]
    assert provenance[evaluations[0].evaluation_id]["type"] == "plan_parameter"


def test_plan_operations_are_whitelisted_and_dependency_ordered():
    operations = [
        PlanOperation("step.load", "load_step"),
        PlanOperation("step.topology", "inspect_topology", ["step.load"]),
        PlanOperation("step.draft", "measure_draft", ["step.topology"]),
    ]
    assert validate_operations(operations) == [
        "load_step",
        "inspect_topology",
        "measure_draft",
    ]

    with pytest.raises(DFMError, match="unsupported STEP operation"):
        validate_operations([
            PlanOperation("step.load", "load_step"),
            PlanOperation("step.topology", "inspect_topology", ["step.load"]),
            PlanOperation("step.exec", "run_arbitrary_python", ["step.topology"]),
        ])


def test_plan_operations_reject_forward_dependencies():
    with pytest.raises(DFMError, match="dependency ordered"):
        validate_operations([
            PlanOperation("step.load", "load_step"),
            PlanOperation("step.draft", "measure_draft", ["step.topology"]),
            PlanOperation("step.topology", "inspect_topology", ["step.load"]),
        ])


def test_every_legacy_issue_code_has_a_versioned_catalog_entry():
    sources = [Path("tools/dfm/geometry/step/legacy_analyzer.py")]
    sources.extend(Path("tools/dfm/geometry/step/checks").glob("*.py"))
    produced = set()
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        produced.update(
            node.args[2].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == "make_issue")
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "make_issue"
                )
            )
            and len(node.args) > 2
            and isinstance(node.args[2], ast.Constant)
            and isinstance(node.args[2].value, str)
        )

    assert produced <= set(issue_catalog())


def test_every_quantitative_catalog_issue_has_an_explicit_metric_mapping():
    quantitative = {
        code for code, item in issue_catalog().items() if item["parameter"] is not None
    }
    assert quantitative <= set(_ISSUE_METRICS)


def test_issue_catalog_is_bound_to_the_worker_algorithm_version():
    payload = json.loads(
        Path("tools/dfm/scopes/injection/legacy_issue_catalog_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["algorithm_version"] == WORKER_VERSION


def test_legacy_compatibility_module_no_longer_owns_check_family_entry_points():
    tree = ast.parse(
        Path("tools/dfm/geometry/step/legacy_analyzer.py").read_text(encoding="utf-8")
    )
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert not names.intersection({
        "analyze_plane_pairs",
        "analyze_face_quality",
        "analyze_cylindrical_dfm",
        "analyze_thickness_field",
        "analyze_surface_continuity",
        "analyze_undercut_slider",
        "render_issue_evidence",
        "render_outputs",
        "export_highlighted_step",
        "write_json_report",
        "write_markdown_report",
    })


def test_extracted_modules_only_reference_real_compatibility_helpers():
    from tools.dfm.geometry.step import legacy_analyzer

    sources = [*Path("tools/dfm/geometry/step/checks").glob("*.py")]
    sources.extend([
        Path("tools/dfm/geometry/step/evidence/rendering.py"),
        Path("tools/dfm/reporting/legacy_reports.py"),
    ])
    missing = []
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "legacy"
                and not hasattr(legacy_analyzer, node.attr)
            ):
                missing.append((source.as_posix(), node.lineno, node.attr))
    assert missing == []


@pytest.mark.skipif(
    not occ_available(), reason="selective STEP execution requires pythonocc-core"
)
def test_persisted_operations_can_run_topology_without_other_checks_or_evidence(
    tmp_path,
):
    from tools.dfm.geometry.step import legacy_analyzer

    fixture = Path("tests/fixtures/dfm/step/injection_plate_with_hole.step").resolve()
    output = tmp_path / "topology-only"
    assert (
        legacy_analyzer.main([
            str(fixture),
            "--out",
            str(output),
            "--operation",
            "load_step",
            "--operation",
            "inspect_topology",
        ])
        == 0
    )

    report = __import__("json").loads(
        (output / "dfm_report.json").read_text(encoding="utf-8")
    )
    assert report["stats"]["valid_brep"] is True
    assert report["issue_count"] == 0
    assert report["evidence"]["rendered_findings"] == 0
    assert report["highlighted_step"] is None
    assert not list(output.glob("*.png"))


@pytest.mark.skipif(
    not occ_available(), reason="selective STEP execution requires pythonocc-core"
)
@pytest.mark.parametrize(
    ("operation", "family"),
    [
        ("inspect_small_features", "small_features"),
        ("measure_planar_spacing", "planar_spacing"),
        ("inspect_face_quality", "face_quality"),
        ("inspect_cylindrical_features", "cylindrical"),
        ("measure_wall_thickness", "thickness"),
        ("measure_draft", "draft"),
        ("inspect_surface_continuity", "continuity"),
        ("inspect_undercut", "undercut"),
    ],
)
def test_each_persisted_operation_isolated_to_its_check_family(
    tmp_path, operation, family
):
    import json

    from tools.dfm.geometry.step import legacy_analyzer

    fixture = Path("tests/fixtures/dfm/step/injection_plate_with_hole.step").resolve()
    output = tmp_path / operation
    assert (
        legacy_analyzer.main([
            str(fixture),
            "--out",
            str(output),
            "--operation",
            "load_step",
            "--operation",
            "inspect_topology",
            "--operation",
            operation,
        ])
        == 0
    )

    report = json.loads((output / "dfm_report.json").read_text(encoding="utf-8"))
    catalog = issue_catalog()
    assert {catalog[item["code"]]["family"] for item in report["issues"]} <= {family}
    assert report["evidence"]["rendered_findings"] == 0
    assert not list(output.glob("*.png"))
