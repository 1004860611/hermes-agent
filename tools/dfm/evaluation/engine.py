"""Evaluate persisted measurements against a persisted DFM plan in Hermes."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import operator
from pathlib import Path
from typing import Any, Callable

from ..contracts import (
    ArtifactRecord,
    EvaluationRecord,
    MeasurementRecord,
    PlanRecord,
    RuleBinding,
)
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
            binding = self._binding(measurement, plan)
            spec = (
                {
                    "rule_id": binding.rule_id,
                    "operator": binding.operator,
                    "aggregation": binding.aggregation,
                }
                if binding is not None
                else (None if plan.rule_bindings else self._legacy_spec(measurement, plan))
            )
            if spec is None:
                continue
            rule_id = str(spec["rule_id"])
            operation_name = str(spec["operator"])
            comparison = _OPERATORS.get(operation_name)
            if comparison is None:
                raise DFMError(
                    "evaluation_rule_invalid",
                    "Evaluation operator is not supported.",
                    {
                        "operator": operation_name,
                        "measurement_id": measurement.measurement_id,
                    },
                )
            parameter = plan.rules.get(rule_id)
            if parameter is not None:
                expected = parameter.value
                source = {
                    "type": "effective_rule",
                    "binding_id": binding.binding_id if binding else None,
                    "aggregation": spec.get("aggregation"),
                    "source": parameter.source,
                    "version": parameter.version,
                    "unit": parameter.unit,
                }
            else:
                if binding is not None:
                    raise DFMError(
                        "evaluation_rule_missing",
                        "A bound production rule is absent from the effective rule set.",
                        {
                            "binding_id": binding.binding_id,
                            "rule_id": rule_id,
                            "measurement_id": measurement.measurement_id,
                        },
                    )
                expected = spec.get("fallback_expected")
                source = {
                    "type": "measurement_rule_snapshot",
                    "source": "step_adapter",
                }
            if expected is None:
                raise DFMError(
                    "evaluation_rule_missing",
                    "No effective parameter exists for a measured check.",
                    {
                        "rule_id": rule_id,
                        "measurement_id": measurement.measurement_id,
                    },
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
            rule_version = parameter.version if parameter is not None else plan.scope_version or "1"
            rule_hash = hashlib.sha256(
                json.dumps(
                    {
                        "rule_id": rule_id,
                        "rule_version": rule_version,
                        "operator": operation_name,
                        "expected": expected,
                        "unit": measurement.unit,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            evaluation = EvaluationRecord(
                evaluation_id=f"evaluation-{legacy_id.lower()}",
                operation_id=measurement.operation_id,
                metric_id=measurement.metric_id,
                measurement_ids=[measurement.measurement_id],
                rule_id=rule_id,
                rule_version=rule_version,
                rule_hash=rule_hash,
                operator=operation_name,
                expected=expected,
                actual=measurement.value,
                outcome="pass" if passed else "fail",
                feature_refs=sorted(
                    set(measurement.feature_refs)
                    | set(binding.feature_refs if binding else [])
                ),
                region_refs=sorted(
                    set(measurement.region_refs)
                    | set(binding.region_refs if binding else [])
                ),
            )
            results.append(evaluation)
            provenance[evaluation.evaluation_id] = source
        return results, provenance

    @staticmethod
    def _binding(
        measurement: MeasurementRecord, plan: PlanRecord
    ) -> RuleBinding | None:
        matches = [
            item
            for item in plan.rule_bindings
            if item.operation_id == measurement.operation_id
            and item.metric_id == measurement.metric_id
            and item.quantity_id == measurement.quantity_id
        ]
        if len(matches) > 1:
            raise DFMError(
                "evaluation_binding_invalid",
                "More than one rule binding matches a measurement.",
                {"measurement_id": measurement.measurement_id},
            )
        if matches:
            return matches[0]
        return None

    @staticmethod
    def _legacy_spec(
        measurement: MeasurementRecord, plan: PlanRecord
    ) -> dict[str, Any] | None:
        if (
            plan.process == "die_casting"
            and measurement.operation_id == "geometry.topology"
            and measurement.quantity_id == "valid_brep"
        ):
            return {
                "rule_id": "valid_brep_required",
                "operator": "==",
                "fallback_expected": True,
            }
        hint = measurement.diagnostics.get("evaluation_hint")
        return dict(hint) if isinstance(hint, dict) else None
