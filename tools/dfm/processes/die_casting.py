"""Die-casting process adapter with an isolated, versioned first scope."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ..analyzers.base import AnalyzerContext
from ..contracts import Capability, CapabilityStatus, EffectiveParameter, PlanOperation
from ..errors import DFMError
from .base import ProcessPlan


class DieCastingProcessAdapter:
    key = "die_casting"
    version = "die-casting-v1"

    def __init__(self, scope_path: Path | None = None) -> None:
        self.scope_path = scope_path or (
            Path(__file__).resolve().parents[1]
            / "scopes"
            / "die_casting"
            / "baseline_v1.json"
        )

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.AVAILABLE,
            "The die-casting process adapter is available for the approved topology gate.",
            details={
                "adapter_version": self.version,
                "available_operations": ["load_step", "inspect_topology"],
                "pending_rule_approval": [
                    "measure_wall_thickness",
                    "measure_draft",
                    "inspect_undercut",
                ],
            },
        )

    def required_facts(self) -> Mapping[str, str]:
        return {
            "model_units": "What length unit was used to author the die-cast part model?",
        }

    def compile(
        self,
        context: AnalyzerContext,
        raw_parameters: Mapping[str, Any],
    ) -> ProcessPlan:
        if raw_parameters:
            raise DFMError(
                "process_parameter_invalid",
                "The initial die-casting topology scope does not accept rule overrides.",
                {"parameters": sorted(raw_parameters)},
            )
        scope = self._load_scope()
        return ProcessPlan(
            process=self.key,
            adapter_version=self.version,
            scope_id=str(scope["scope_id"]),
            scope_version=str(scope["version"]),
            parameters={
                key: EffectiveParameter(
                    definition["value"],
                    definition.get("unit"),
                    "die_casting_baseline_default",
                    str(definition.get("kind") or "engineering_context"),
                )
                for key, definition in scope["parameters"].items()
            },
            operations=[PlanOperation.from_dict(item) for item in scope["operations"]],
        )

    def _load_scope(self) -> dict[str, Any]:
        try:
            scope = json.loads(self.scope_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DFMError(
                "process_scope_invalid",
                "The die-casting baseline scope could not be loaded.",
                {"path": str(self.scope_path)},
            ) from exc
        if (
            scope.get("scope_id") != "die_casting.topology-baseline"
            or scope.get("version") != "1.0.0"
            or scope.get("process") != self.key
            or not isinstance(scope.get("parameters"), dict)
            or not isinstance(scope.get("operations"), list)
        ):
            raise DFMError(
                "process_scope_invalid",
                "The die-casting baseline scope has an invalid contract.",
            )
        return scope
