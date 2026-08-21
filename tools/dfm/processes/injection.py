"""Backend-neutral injection plan for the OCCT geometry-core scope."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from ..analyzers.base import AnalyzerContext
from ..contracts import (
    Capability,
    CapabilityStatus,
    EffectiveRule,
    PlanOperation,
    ResolvedArgument,
    RuleBinding,
)
from ..errors import DFMError
from .base import ProcessPlan


_TRUSTED_SOURCES = {"project_fact", "user_confirmed"}
_LENGTH_UNIT_ALIASES = {
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
    "cm": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "in": "inch",
    "inch": "inch",
    "inches": "inch",
    "ft": "foot",
    "foot": "foot",
    "feet": "foot",
}


class InjectionProcessAdapter:
    key = "injection"
    version = "injection-geometry-core-v4"

    def __init__(self, scope_path: Path | None = None) -> None:
        self.scope_path = scope_path or (
            Path(__file__).resolve().parents[1]
            / "scopes"
            / "injection"
            / "geometry_core_v4.json"
        )

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.AVAILABLE,
            "The backend-neutral injection geometry-core scope is available.",
            details={"adapter_version": self.version},
        )

    def required_facts(self) -> Mapping[str, str]:
        return {
            "model_units": "What length unit was used to author the STEP model?",
        }

    def compile(
        self,
        context: AnalyzerContext,
        raw_parameters: Mapping[str, Any],
    ) -> ProcessPlan:
        scope = self._load_scope()
        defaults = scope["parameters"]
        unknown = sorted(set(raw_parameters) - set(defaults))
        if unknown:
            self._invalid("Unknown injection parameter.", {"parameters": unknown})

        resolved = {
            key: {
                "value": self._normalize_value(key, definition["value"]),
                "unit": definition.get("unit"),
                "source": "injection_scope_default",
                "source_ref": (
                    f"scope:{scope['scope_id']}@{scope['version']}/parameters/{key}"
                ),
                "kind": str(definition.get("kind") or "rule"),
            }
            for key, definition in defaults.items()
        }
        for key, raw in raw_parameters.items():
            source = "project_fact"
            value = raw
            if isinstance(raw, Mapping):
                value = raw.get("value")
                source = str(raw.get("source") or "")
            if source not in _TRUSTED_SOURCES:
                self._invalid(
                    "Injection parameter source is not trusted.",
                    {"parameter": key, "source": source},
                )
            resolved[key] = {
                "value": self._normalize_value(key, value),
                "unit": defaults[key].get("unit"),
                "source": source,
                "source_ref": str(raw.get("source_ref") or f"fact:{key}")
                if isinstance(raw, Mapping)
                else f"fact:{key}",
                "kind": str(defaults[key].get("kind") or "rule"),
            }

        rules = {
            key: EffectiveRule(
                value=item["value"],
                unit=item["unit"],
                source=item["source_ref"],
                version=str(scope["version"]),
            )
            for key, item in resolved.items()
            if item["kind"] == "rule"
        }
        operations = [PlanOperation.from_dict(item) for item in scope["operations"]]
        enriched_operations = []
        for operation in operations:
            arguments = dict(operation.arguments)
            algorithm_options = dict(operation.algorithm_options)
            if operation.calculator_id == "geometry_preflight":
                units = resolved["model_units"]
                arguments["model_unit"] = ResolvedArgument(
                    units["value"], units["source_ref"], None
                )
            elif operation.calculator_id in {"measure_draft", "measure_undercut"}:
                pull = resolved["pull_dir"]
                arguments["pull_direction"] = ResolvedArgument(
                    pull["value"], pull["source_ref"], pull["unit"]
                )
            enriched_operations.append(
                PlanOperation(
                    operation_id=operation.operation_id,
                    calculator_id=operation.calculator_id,
                    depends_on=operation.depends_on,
                    metric_ids=operation.metric_ids,
                    required_quantities=operation.required_quantities,
                    required_artifacts=operation.required_artifacts,
                    arguments=arguments,
                    algorithm_options=algorithm_options,
                )
            )

        return ProcessPlan(
            process=self.key,
            adapter_version=self.version,
            scope_id=scope["scope_id"],
            scope_version=scope["version"],
            rules=rules,
            operations=enriched_operations,
            accepted_inputs=set(defaults),
            rule_bindings=[
                RuleBinding.from_dict(item)
                for item in scope["rule_bindings"]
            ],
        )

    def _load_scope(self) -> dict[str, Any]:
        try:
            scope = json.loads(self.scope_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DFMError(
                "process_scope_invalid",
                "The injection default analysis scope could not be loaded.",
                {"path": str(self.scope_path)},
            ) from exc
        if (
            scope.get("scope_id") != "injection.geometry-core"
            or scope.get("version") != "4.0.0"
            or scope.get("process") != self.key
            or not isinstance(scope.get("parameters"), dict)
            or not isinstance(scope.get("operations"), list)
            or not isinstance(scope.get("rule_bindings"), list)
        ):
            raise DFMError(
                "process_scope_invalid",
                "The injection default analysis scope has an invalid contract.",
            )
        return scope

    def _normalize_value(self, key: str, value: Any) -> Any:
        if key == "model_units":
            unit = str(value or "").strip().lower()
            if unit not in _LENGTH_UNIT_ALIASES:
                self._invalid(
                    "model_units must identify a supported STEP length unit.",
                    {
                        "model_units": value,
                        "supported_units": ["mm", "cm", "m", "inch", "foot"],
                    },
                )
            return _LENGTH_UNIT_ALIASES[unit]
        if key == "pull_dir":
            if not isinstance(value, (list, tuple)) or len(value) != 3:
                self._invalid("pull_dir must contain exactly three numbers.")
            try:
                vector = [float(item) for item in value]
            except (TypeError, ValueError) as exc:
                raise DFMError(
                    "process_parameter_invalid",
                    "pull_dir must contain exactly three numbers.",
                ) from exc
            if not all(math.isfinite(item) for item in vector) or not any(vector):
                self._invalid("pull_dir must be a finite non-zero vector.")
            return vector
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DFMError(
                "process_parameter_invalid",
                f"Injection parameter must be numeric: {key}",
                {"parameter": key},
            ) from exc
        allow_zero = key == "max_undercut_count"
        if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
            self._invalid(
                "Injection parameter must be a positive finite number.",
                {"parameter": key},
            )
        return number

    @staticmethod
    def _invalid(message: str, details: dict[str, Any] | None = None) -> None:
        raise DFMError("process_parameter_invalid", message, details)
