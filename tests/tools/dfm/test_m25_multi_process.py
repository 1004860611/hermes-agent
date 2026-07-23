import json

from tools.dfm.contracts import ArtifactRecord
from tools.dfm.findings import materialize_findings
from tools.dfm.geometry.brep.checks import resolve_brep_check
from tools.dfm.geometry.step.measurements import normalize_legacy_issues


def test_step_operations_resolve_through_format_independent_brep_registry():
    assert resolve_brep_check("measure_wall_thickness") == "thickness"
    assert resolve_brep_check("measure_draft") == "draft"


def test_die_casting_topology_gate_has_process_specific_evaluation_and_finding(
    tmp_path,
):
    measurements, evaluations = normalize_legacy_issues(
        [],
        input_sha256="c" * 64,
        algorithm_version="step-m12-v1",
        stats={"valid_brep": False},
        process="die_casting",
    )

    assert any(item.metric == "valid_brep" for item in measurements)
    assert len(evaluations) == 1
    assert evaluations[0].check_id == "invalid_brep"
    assert evaluations[0].measurement_refs == [
        next(item.measurement_id for item in measurements if item.metric == "valid_brep")
    ]
    assert evaluations[0].parameter_ref == "valid_brep_required"
    assert evaluations[0].outcome == "fail"

    path = tmp_path / "measurements.json"
    path.write_text(
        json.dumps(
            {
                "input_sha256": "c" * 64,
                "process": "die_casting",
                "measurements": [item.to_dict() for item in measurements],
                "evaluations": [item.to_dict() for item in evaluations],
            }
        ),
        encoding="utf-8",
    )
    findings = materialize_findings(
        tmp_path,
        [
            ArtifactRecord(
                "m", "measurements", "measurements.json", "application/json", "now"
            )
        ],
    )

    assert findings[0].rule_ref == "die_casting.baseline-issues@1.0.0:invalid_brep"
