"""Finding materializers for the legacy STEP and evaluated field pipelines."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import ArtifactRecord, FindingRecord
from .errors import DFMError


def materialize_legacy_step_findings(
    project_dir: Path, artifacts: list[ArtifactRecord]
) -> list[FindingRecord]:
    """Adapt historical STEP reports without changing their artifact contract."""

    by_kind = {item.kind: item for item in artifacts}
    measurements = by_kind.get("measurements")
    evaluations_artifact = by_kind.get("evaluations")
    if measurements is None or evaluations_artifact is None:
        return []
    try:
        payload = json.loads((project_dir / measurements.relative_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DFMError("measurements_invalid", "The DFM measurements artifact could not be read.") from exc
    if not isinstance(payload, dict):
        raise DFMError("measurements_invalid", "The DFM measurements artifact has an invalid contract.")
    try:
        evaluation_payload = json.loads(
            (project_dir / evaluations_artifact.relative_path).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError) as exc:
        raise DFMError(
            "evaluations_invalid",
            "The DFM evaluations artifact could not be read.",
        ) from exc
    evaluations = evaluation_payload.get("evaluations")
    if not isinstance(evaluations, list):
        raise DFMError("evaluations_invalid", "The DFM evaluations artifact has an invalid contract.")

    report_issues = _report_issues(project_dir, by_kind.get("report_json"))
    evidence_refs = [
        item.relative_path
        for item in artifacts
        if item.kind in {"measurements", "evaluations", "report_json", "report_markdown", "evidence_image", "highlighted_step"}
    ]
    input_hash = str(payload.get("input_sha256") or "")
    process = str(payload.get("process") or "injection")
    if process == "die_casting":
        catalog_id, catalog_version = "die_casting.baseline-issues", "1.0.0"
    else:
        catalog_id, catalog_version = "injection.legacy-issues", "1.0.0"
    results = []
    for evaluation in evaluations:
        if not isinstance(evaluation, dict) or evaluation.get("outcome") != "fail":
            continue
        rule_id = str(evaluation.get("rule_id") or "unmapped")
        metric_id = str(evaluation.get("metric_id") or "unmapped")
        measurement_ids = [str(item) for item in evaluation.get("measurement_ids") or []]
        linked_measurements = [
            item
            for item in payload.get("measurements") or []
            if isinstance(item, dict) and item.get("measurement_id") in measurement_ids
        ]
        issue = report_issues.get(_legacy_issue_id(evaluation)) or {}
        evaluation_id = str(evaluation.get("evaluation_id") or rule_id)
        stable = hashlib.sha256(f"{input_hash}:{evaluation_id}".encode("utf-8")).hexdigest()[:20]
        results.append(
            FindingRecord(
                finding_id=f"finding_{stable}",
                title=str(issue.get("title") or rule_id.replace("_", " ").title()),
                severity=str(issue.get("severity") or "unclassified"),
                status="open",
                evaluation_ids=[evaluation_id],
                measurement_ids=measurement_ids,
                metric_ids=[metric_id],
                region_refs=sorted({
                    str(ref)
                    for item in linked_measurements
                    for ref in item.get("region_refs") or []
                }),
                evidence_refs=evidence_refs,
                rule_refs=[
                    f"{catalog_id}@{catalog_version}:{rule_id}",
                    f"sha256:{evaluation.get('rule_hash')}",
                ],
                recommendation=str(issue.get("recommendation") or "Review the measured geometry against the referenced rule."),
            )
        )
    return results


def materialize_evaluated_findings(
    project_dir: Path, artifacts: list[ArtifactRecord]
) -> list[FindingRecord]:
    """Create production findings from explicit evaluations and evidence records."""

    by_kind = {item.kind: item for item in artifacts}
    measurements_artifact = by_kind.get("measurements")
    evaluations_artifact = by_kind.get("evaluations")
    if measurements_artifact is None or evaluations_artifact is None:
        return []
    measurements_payload = _read_object(
        project_dir, measurements_artifact, "measurements_invalid"
    )
    evaluations_payload = _read_object(
        project_dir, evaluations_artifact, "evaluations_invalid"
    )
    evidence_payload = (
        _read_object(project_dir, by_kind["evidence_records"], "evidence_invalid")
        if "evidence_records" in by_kind
        else {"records": []}
    )
    measurements = {
        str(item.get("measurement_id")): item
        for item in measurements_payload.get("measurements", [])
        if isinstance(item, dict) and item.get("measurement_id")
    }
    evidence_by_evaluation: dict[str, list[str]] = {}
    for record in evidence_payload.get("records", []):
        if not isinstance(record, dict) or not record.get("evidence_id"):
            continue
        for evaluation_id in record.get("evaluation_ids", []):
            evidence_by_evaluation.setdefault(str(evaluation_id), []).append(
                str(record["evidence_id"])
            )

    input_hash = str(measurements_payload.get("input_sha256") or "")
    results = []
    for evaluation in evaluations_payload.get("evaluations", []):
        if not isinstance(evaluation, dict) or evaluation.get("outcome") != "fail":
            continue
        evaluation_id = str(evaluation.get("evaluation_id") or "")
        measurement_ids = [
            str(item) for item in evaluation.get("measurement_ids", [])
        ]
        linked = [measurements[item] for item in measurement_ids if item in measurements]
        rule_id = str(evaluation.get("rule_id") or "unmapped")
        rule_version = str(evaluation.get("rule_version") or "1")
        stable = hashlib.sha256(
            f"{input_hash}:{evaluation_id}".encode("utf-8")
        ).hexdigest()[:20]
        results.append(
            FindingRecord(
                finding_id=f"finding_{stable}",
                title=rule_id.replace(".", " ").replace("_", " ").title(),
                severity="unclassified",
                status="open",
                evaluation_ids=[evaluation_id],
                measurement_ids=measurement_ids,
                metric_ids=[str(evaluation.get("metric_id") or "unmapped")],
                region_refs=sorted({
                    str(ref)
                    for item in linked
                    for ref in item.get("region_refs", [])
                }),
                evidence_refs=sorted(evidence_by_evaluation.get(evaluation_id, [])),
                rule_refs=[
                    f"{rule_id}@{rule_version}",
                    f"sha256:{evaluation.get('rule_hash')}",
                ],
                recommendation="Review and correct the geometry identified by the evaluated rule.",
            )
        )
    return results


def _legacy_issue_id(evaluation: dict) -> str:
    return str(evaluation.get("evaluation_id") or "").removeprefix("evaluation-")


def _report_issues(project_dir: Path, artifact: ArtifactRecord | None) -> dict[str, dict]:
    if artifact is None:
        return {}
    try:
        report = json.loads((project_dir / artifact.relative_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(item.get("id")): item
        for item in report.get("issues", [])
        if isinstance(item, dict) and item.get("id")
    }


def _read_object(
    project_dir: Path, artifact: ArtifactRecord, error_code: str
) -> dict:
    try:
        payload = json.loads(
            (project_dir / artifact.relative_path).read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise DFMError(error_code, f"The {artifact.kind} artifact could not be read.") from exc
    if not isinstance(payload, dict):
        raise DFMError(error_code, f"The {artifact.kind} artifact has an invalid contract.")
    return payload
