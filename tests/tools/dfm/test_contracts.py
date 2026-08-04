import json

import pytest

from tools.dfm.contracts import (
    MANIFEST_SCHEMA_VERSION,
    ArtifactRecord,
    Capability,
    CapabilityStatus,
    ClarificationRecord,
    FactRecord,
    FeatureRecord,
    FindingRecord,
    InputRecord,
    MeasurementRecord,
    PlanOperation,
    PlanRecord,
    ProjectManifest,
    RunRecord,
    RunStatus,
    ensure_run_transition,
)
from tools.dfm.errors import DFMError


def test_contract_state_values_are_stable():
    assert {item.value for item in CapabilityStatus} == {
        "available",
        "dependency_missing",
        "not_implemented",
        "disabled",
        "unhealthy",
    }
    assert {item.value for item in RunStatus} == {
        "queued",
        "running",
        "succeeded",
        "failed",
        "cancelled",
        "blocked",
    }


def test_manifest_contract_serializes_to_json_compatible_dict():
    manifest = ProjectManifest(
        project_id="dfm_123",
        name="Bracket",
        created_at="2026-07-13T10:00:00Z",
        updated_at="2026-07-13T10:01:00Z",
        inputs=[
            InputRecord(
                input_id="input_1",
                kind="step",
                source_name="bracket.step",
                relative_path="inputs/bracket.step",
                size_bytes=12,
                sha256="a" * 64,
                created_at="2026-07-13T10:00:10Z",
            )
        ],
        runs=[
            RunRecord(
                run_id="run_1",
                analyzer_key="step",
                analyzer_version="unimplemented",
                status=RunStatus.SUCCEEDED,
                created_at="2026-07-13T10:00:20Z",
                updated_at="2026-07-13T10:01:00Z",
                artifacts=[
                    ArtifactRecord(
                        artifact_id="artifact_1",
                        kind="diagnostic",
                        relative_path="artifacts/run_1/status.json",
                        media_type="application/json",
                        created_at="2026-07-13T10:01:00Z",
                    )
                ],
            )
        ],
    )

    payload = manifest.to_dict()

    assert payload["schema_version"] == MANIFEST_SCHEMA_VERSION == 1
    assert payload["runs"][0]["status"] == "succeeded"
    assert json.loads(json.dumps(payload)) == payload


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.QUEUED, RunStatus.RUNNING),
        (RunStatus.QUEUED, RunStatus.CANCELLED),
        (RunStatus.QUEUED, RunStatus.BLOCKED),
        (RunStatus.RUNNING, RunStatus.SUCCEEDED),
        (RunStatus.RUNNING, RunStatus.FAILED),
        (RunStatus.RUNNING, RunStatus.CANCELLED),
    ],
)
def test_valid_run_transitions_are_accepted(current, target):
    ensure_run_transition(current, target)


def test_terminal_run_transition_is_rejected():
    with pytest.raises(DFMError) as exc_info:
        ensure_run_transition(RunStatus.SUCCEEDED, RunStatus.RUNNING)

    assert exc_info.value.code == "invalid_run_transition"


def test_capability_and_error_envelopes_are_stable():
    capability = Capability(
        analyzer_key="drawing",
        status=CapabilityStatus.NOT_IMPLEMENTED,
        reason="Drawing analysis is planned for a later milestone.",
        error_code="unsupported_capability",
    )
    error = DFMError(
        "unsupported_capability",
        "Drawing analysis is not implemented.",
        {"analyzer_key": "drawing"},
    )

    assert capability.to_dict() == {
        "analyzer_key": "drawing",
        "status": "not_implemented",
        "reason": "Drawing analysis is planned for a later milestone.",
        "error_code": "unsupported_capability",
        "details": {},
    }
    assert error.to_dict() == {
        "ok": False,
        "error": {
            "code": "unsupported_capability",
            "message": "Drawing analysis is not implemented.",
            "details": {"analyzer_key": "drawing"},
        },
    }


def test_manifest_carries_m0_workflow_records():
    manifest = ProjectManifest(
        project_id="dfm_123",
        name="Bracket",
        created_at="2026-07-13T10:00:00Z",
        updated_at="2026-07-13T10:01:00Z",
        domain="injection_molding",
        input_mode="step",
        facts=[FactRecord("fact_1", "material", "ABS", "user", "confirmed")],
        clarifications=[
            ClarificationRecord("clar_1", "Which material?", "answered", "ABS")
        ],
        features=[FeatureRecord("feature_1", "hole", ["input_1"], 0.9)],
        plans=[PlanRecord("plan_1", "step", ["step"], "ready", "2026-07-13T10:00:30Z")],
        findings=[
            FindingRecord(
                "finding_1",
                "Thin wall",
                "high",
                "open",
                ["artifact_1"],
                "rule:wall-thickness:v1",
                "Increase local thickness.",
            )
        ],
    )

    restored = ProjectManifest.from_dict(manifest.to_dict())

    assert restored == manifest
    assert restored.revision == 0
    assert restored.facts[0].status == "confirmed"


def test_plan_operation_v2_round_trips_and_keeps_v1_shape_stable():
    legacy = PlanOperation("geometry.topology", "inspect_topology", ["geometry.load"])
    operation = PlanOperation(
        "draft.fixed_half",
        "measure_draft",
        ["geometry.topology"],
        ["dc.geometry.draft.fixed_half"],
        {
            "pull_direction": {"fact_ref": "pull_direction.fixed_half"},
            "region": {"region_ref": "region.fixed_half"},
        },
    )

    assert legacy.to_dict() == {
        "operation_id": "geometry.topology",
        "operation": "inspect_topology",
        "depends_on": ["geometry.load"],
    }
    payload = operation.to_nx_dict(2)
    assert payload["calculator_id"] == "measure_draft"
    assert "operation" not in payload
    assert PlanOperation.from_dict(payload) == operation


def test_measurement_v2_references_plan_operation_metric_and_calculator():
    measurement = MeasurementRecord(
        "measurement_draft_fixed_half_min",
        "draft.fixed_half",
        "draft_angle_deg",
        1.2,
        "degree",
        "measured",
        [],
        "nx_open_draft_analysis",
        "nx-draft-v1",
        "a" * 64,
        operation_ref="draft.fixed_half",
        calculator_id="measure_draft",
        metric_id="dc.geometry.draft.fixed_half",
    )

    assert MeasurementRecord.from_dict(measurement.to_dict()) == measurement
