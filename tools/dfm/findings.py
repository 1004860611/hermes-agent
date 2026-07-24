"""Project-level Finding normalization from deterministic STEP artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import ArtifactRecord, FindingRecord
from .errors import DFMError


def materialize_findings(
    project_dir: Path, artifacts: list[ArtifactRecord]
) -> list[FindingRecord]:
    """Create stable findings without changing legacy report artifacts."""

    by_kind = {item.kind: item for item in artifacts}
    measurements = by_kind.get("measurements")
    evaluations_artifact = by_kind.get("evaluations")
    if measurements is None:
        return []
    try:
        payload = json.loads((project_dir / measurements.relative_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DFMError("measurements_invalid", "The DFM measurements artifact could not be read.") from exc
    if not isinstance(payload, dict):
        raise DFMError("measurements_invalid", "The DFM measurements artifact has an invalid contract.")
    if evaluations_artifact is not None:
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
    else:
        # Read-only compatibility for historical runs created before the
        # Hermes EvaluationEngine produced a separate artifact.
        evaluations = payload.get("evaluations")
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
        check_id = str(evaluation.get("check_id") or "unmapped")
        issue = report_issues.get(_legacy_issue_id(evaluation)) or {}
        evaluation_id = str(evaluation.get("evaluation_id") or check_id)
        stable = hashlib.sha256(f"{input_hash}:{evaluation_id}".encode("utf-8")).hexdigest()[:20]
        results.append(
            FindingRecord(
                finding_id=f"finding_{stable}",
                title=str(issue.get("title") or check_id.replace("_", " ").title()),
                severity=str(issue.get("severity") or "unclassified"),
                status="open",
                evidence_refs=evidence_refs,
                rule_ref=f"{catalog_id}@{catalog_version}:{check_id}",
                recommendation=str(issue.get("recommendation") or "Review the measured geometry against the referenced rule."),
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
