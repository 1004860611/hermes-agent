"""Stable process-adapter boundary for DFM plan compilation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from ..analyzers.base import AnalyzerContext
from ..contracts import Capability, EffectiveParameter, PlanOperation


@dataclass(frozen=True)
class ProcessPlan:
    process: str
    adapter_version: str
    scope_id: str
    scope_version: str
    parameters: dict[str, EffectiveParameter]
    operations: list[PlanOperation]


@runtime_checkable
class ProcessAdapter(Protocol):
    key: str
    version: str

    def capability(self, context: AnalyzerContext) -> Capability: ...

    def required_facts(self) -> Mapping[str, str]: ...

    def compile(
        self,
        context: AnalyzerContext,
        raw_parameters: Mapping[str, Any],
    ) -> ProcessPlan: ...
