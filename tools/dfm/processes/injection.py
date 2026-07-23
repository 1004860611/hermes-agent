"""Injection-molding adapter for the M1 legacy STEP baseline."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

from ..analyzers.base import AnalyzerContext
from ..contracts import (
    Capability,
    CapabilityStatus,
    EffectiveParameter,
    PlanOperation,
)
from ..errors import DFMError
from .base import ProcessPlan


_TRUSTED_SOURCES = {"project_fact", "user_confirmed"}


class InjectionProcessAdapter:
    key = "injection"
    version = "legacy-injection-v1"

    def __init__(self, scope_path: Path | None = None) -> None:
        self.scope_path = scope_path or (
            Path(__file__).resolve().parents[1]
            / "scopes"
            / "injection"
            / "legacy_baseline_v1.json"
        )

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.AVAILABLE,
            "The injection process adapter and legacy baseline scope are available.",
            details={"adapter_version": self.version},
        )

    def required_facts(self) -> Mapping[str, str]:
        return {
            "material": "What resin/material grade will be used for this part?",
            "pull_dir": "What is the confirmed mold pull direction as [x, y, z]?",
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

        parameters = {
            key: EffectiveParameter(
                self._normalize_value(key, definition["value"]),
                definition.get("unit"),
                "injection_legacy_default",
                str(definition.get("kind") or "rule"),
            )
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
            parameters[key] = EffectiveParameter(
                self._normalize_value(key, value),
                defaults[key].get("unit"),
                source,
                str(defaults[key].get("kind") or "rule"),
            )

        return ProcessPlan(
            process=self.key,
            adapter_version=self.version,
            scope_id=scope["scope_id"],
            scope_version=scope["version"],
            parameters=parameters,
            operations=[PlanOperation.from_dict(item) for item in scope["operations"]],
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
            scope.get("scope_id") != "injection.legacy-baseline"
            or scope.get("version") != "1.1.0"
            or scope.get("process") != self.key
            or not isinstance(scope.get("parameters"), dict)
            or not isinstance(scope.get("operations"), list)
        ):
            raise DFMError(
                "process_scope_invalid",
                "The injection default analysis scope has an invalid contract.",
            )
        return scope

    def _normalize_value(self, key: str, value: Any) -> Any:
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
        if not math.isfinite(number) or number <= 0:
            self._invalid(
                "Injection parameter must be a positive finite number.",
                {"parameter": key},
            )
        return number

    @staticmethod
    def _invalid(message: str, details: dict[str, Any] | None = None) -> None:
        raise DFMError("process_parameter_invalid", message, details)
