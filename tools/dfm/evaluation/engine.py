"""Evaluate persisted measurements against a persisted DFM plan in Hermes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import operator
from pathlib import Path
from typing import Any, Callable

from ..contracts import ArtifactRecord, EvaluationRecord, MeasurementRecord, PlanRecord
from ..errors import DFMError


EVALUATION_SCHEMA_VERSION = 1
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


class EvaluationEngine:
    """The sole production owner of Measurement → Evaluation comparison."""

    version = "hermes-evaluation-v1"

    def materialize(
        self,
        project_dir: Path,
        run_id: str,
        plan: PlanRecord,
        artifacts: list[ArtifactRecord],
    ) -> ArtifactRecord:
        measurement_artifact = next(
            (item for item in artifacts if item.kind == "measurements"), None
        )
        if measurement_artifact is None:
            raise DFMError(
                "measurements_invalid",
                "A successful geometry run must provide measurements for evaluation.",
            )
        try:
            payload = json.loads(
                (project_dir / measurement_artifact.relative_path).read_text(
                    encoding="utf-8"
                )
            )
            measurements = [
                MeasurementRecord.from_dict(item)
                for item in payload.get("measurements", [])
            ]
        except (OSError, TypeError, ValueError) as exc:
            raise DFMError(
                "measurements_invalid",
                "The measurements artifact cannot be evaluated.",
            ) from exc
        evaluations, provenance = self.evaluate(measurements, plan)
        output_dir = project_dir / "runs" / run_id / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "evaluations.json"
        output_path.write_text(
            json.dumps(
                {
                    "schema_version": EVALUATION_SCHEMA_VERSION,
                    "engine_version": self.version,
                    "run_id": run_id,
                    "input_sha256": str(payload.get("input_sha256") or ""),
                    "process": plan.process,
                    "scope_id": plan.scope_id,
                    "scope_version": plan.scope_version,
                    "measurement_artifact": measurement_artifact.relative_path,
                    "evaluations": [item.to_dict() for item in evaluations],
                    "provenance": provenance,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return ArtifactRecord(
            f"artifact_{run_id}_evaluations",
            "evaluations",
            output_path.relative_to(project_dir).as_posix(),
            "application/json",
            _utc_now(),
        )

    def evaluate(
        self, measurements: list[MeasurementRecord], plan: PlanRecord
    ) -> tuple[list[EvaluationRecord], dict[str, dict[str, Any]]]:
        results: list[EvaluationRecord] = []
        provenance: dict[str, dict[str, Any]] = {}
        for measurement in measurements:
            spec = self._spec(measurement, plan)
            if spec is None:
                continue
            parameter_ref = str(spec["parameter_ref"])
            operation_name = str(spec["operator"])
            comparison = _OPERATORS.get(operation_name)
            if comparison is None:
                raise DFMError(
                    "evaluation_rule_invalid",
                    "Evaluation operator is not supported.",
                    {"operator": operation_name, "check_id": measurement.check_id},
                )
            parameter = plan.parameters.get(parameter_ref)
            if parameter is not None:
                expected = parameter.value
                source = {
                    "type": "plan_parameter",
                    "source": parameter.source,
                    "kind": parameter.kind,
                    "unit": parameter.unit,
                }
            else:
                expected = spec.get("fallback_expected")
                source = {
                    "type": "legacy_compatibility_hint",
                    "source": "legacy_worker_reported",
                    "migration_required": True,
                }
            if expected is None:
                raise DFMError(
                    "evaluation_rule_missing",
                    "No effective parameter exists for a measured check.",
                    {"parameter_ref": parameter_ref, "check_id": measurement.check_id},
                )
            try:
                passed = bool(comparison(measurement.value, expected))
            except (TypeError, ValueError) as exc:
                raise DFMError(
                    "evaluation_value_invalid",
                    "Measurement and expected value cannot be compared.",
                    {"measurement_id": measurement.measurement_id},
                ) from exc
            legacy_id = str(
                measurement.diagnostics.get("legacy_issue_id")
                or measurement.measurement_id
            )
            evaluation = EvaluationRecord(
                f"evaluation-{legacy_id.lower()}",
                str(spec.get("check_id") or measurement.check_id),
                [measurement.measurement_id],
                parameter_ref,
                operation_name,
                expected,
                measurement.value,
                "pass" if passed else "fail",
            )
            results.append(evaluation)
            provenance[evaluation.evaluation_id] = source
        return results, provenance

    @staticmethod
    def _spec(
        measurement: MeasurementRecord, plan: PlanRecord
    ) -> dict[str, Any] | None:
        if (
            plan.process == "die_casting"
            and measurement.check_id == "model_geometry"
            and measurement.metric == "valid_brep"
        ):
            return {
                "check_id": "invalid_brep",
                "parameter_ref": "valid_brep_required",
                "operator": "==",
                "fallback_expected": True,
            }
        hint = measurement.diagnostics.get("evaluation_hint")
        return dict(hint) if isinstance(hint, dict) else None
