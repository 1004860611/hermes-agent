"""Deterministic registry for production and injected DFM analyzers."""

from __future__ import annotations

from .base import Analyzer
from .drawing import DrawingAnalyzer
from .fusion import FusionAnalyzer
from .step import StepAnalyzer
from ..errors import DFMError


class AnalyzerRegistry:
    def __init__(self) -> None:
        self._analyzers: dict[str, Analyzer] = {}

    def register(self, analyzer: Analyzer) -> None:
        if analyzer.key in self._analyzers:
            raise DFMError(
                "analyzer_duplicate",
                f"DFM analyzer is already registered: {analyzer.key}",
                {"analyzer_key": analyzer.key},
            )
        self._analyzers[analyzer.key] = analyzer

    def get(self, key: str) -> Analyzer:
        try:
            return self._analyzers[key]
        except KeyError as exc:
            raise DFMError(
                "analyzer_not_found",
                f"DFM analyzer is not registered: {key}",
                {"analyzer_key": key},
            ) from exc

    def keys(self) -> list[str]:
        return sorted(self._analyzers)


def build_default_registry() -> AnalyzerRegistry:
    registry = AnalyzerRegistry()
    registry.register(StepAnalyzer())
    registry.register(DrawingAnalyzer())
    registry.register(FusionAnalyzer())
    return registry
