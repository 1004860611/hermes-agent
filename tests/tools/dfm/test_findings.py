import json

from tools.dfm.contracts import ArtifactRecord
from tools.dfm.findings import materialize_findings


def test_measurements_and_legacy_report_normalize_to_stable_finding(tmp_path):
    measurements = tmp_path / "measurements.json"
    measurements.write_text(
        json.dumps(
            {
                "input_sha256": "a" * 64,
                "evaluations": [
                    {
                        "evaluation_id": "evaluation-DFM-001",
                        "check_id": "low_draft",
                        "outcome": "fail",
                    }
                ],
            }
        ),
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
        ArtifactRecord("report", "report_json", "dfm_report.json", "application/json", "now"),
    ]

    first = materialize_findings(tmp_path, artifacts)
    second = materialize_findings(tmp_path, artifacts)

    assert [item.to_dict() for item in first] == [item.to_dict() for item in second]
    assert first[0].title == "Insufficient draft"
    assert first[0].rule_ref == "injection.legacy-issues@1.0.0:low_draft"
    assert first[0].evidence_refs == ["measurements.json", "dfm_report.json"]
