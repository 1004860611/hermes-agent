import json

from tools.dfm.contracts import ArtifactRecord
from tools.dfm.findings import materialize_findings


def test_measurements_evaluations_and_report_normalize_to_stable_finding(tmp_path):
    measurements = tmp_path / "measurements.json"
    measurements.write_text(
        json.dumps(
            {
                "input_sha256": "a" * 64,
                "measurements": [
                    {
                        "measurement_id": "measurement-dfm-001",
                        "region_refs": ["region.fixed-half"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evaluations = tmp_path / "evaluations.json"
    evaluations.write_text(
        json.dumps({
            "evaluations": [{
                "evaluation_id": "evaluation-DFM-001",
                "metric_id": "injection.geometry.draft",
                "measurement_ids": ["measurement-dfm-001"],
                "rule_id": "min_draft_deg",
                "rule_hash": "c" * 64,
                "outcome": "fail",
            }]
        }),
        encoding="utf-8",
    )
    report = tmp_path / "dfm_report.json"
    report.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "id": "DFM-001",
                        "title": "Insufficient draft",
                        "severity": "high",
                        "recommendation": "Increase draft.",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    artifacts = [
        ArtifactRecord("measurements", "measurements", "measurements.json", "application/json", "now"),
        ArtifactRecord("evaluations", "evaluations", "evaluations.json", "application/json", "now"),
        ArtifactRecord("report", "report_json", "dfm_report.json", "application/json", "now"),
    ]

    first = materialize_findings(tmp_path, artifacts)
    second = materialize_findings(tmp_path, artifacts)

    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert first[0].title == "Insufficient draft"
    assert first[0].rule_refs[0] == "injection.legacy-issues@1.0.0:min_draft_deg"
    assert first[0].metric_ids == ["injection.geometry.draft"]
    assert first[0].region_refs == ["region.fixed-half"]
    assert first[0].evidence_refs == [
        "measurements.json", "evaluations.json", "dfm_report.json"
    ]


def test_die_casting_finding_never_uses_injection_rule_reference(tmp_path):
    measurements = tmp_path / "measurements.json"
    measurements.write_text(
        json.dumps(
            {
                "input_sha256": "b" * 64,
                "process": "die_casting",
                "measurements": [
                    {
                        "measurement_id": "measurement-valid-brep",
                        "region_refs": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    evaluations = tmp_path / "evaluations.json"
    evaluations.write_text(
        json.dumps({
            "evaluations": [{
                "evaluation_id": "evaluation-die-casting-valid-brep",
                "metric_id": "geometry.model",
                "measurement_ids": ["measurement-valid-brep"],
                "rule_id": "valid_brep_required",
                "rule_hash": "d" * 64,
                "outcome": "fail",
            }]
        }),
        encoding="utf-8",
    )
    artifacts = [
        ArtifactRecord(
            "measurements",
            "measurements",
            "measurements.json",
            "application/json",
            "now",
        ),
        ArtifactRecord(
            "evaluations", "evaluations", "evaluations.json", "application/json", "now"
        ),
    ]

    finding = materialize_findings(tmp_path, artifacts)[0]

    assert finding.rule_refs[0] == "die_casting.baseline-issues@1.0.0:valid_brep_required"
