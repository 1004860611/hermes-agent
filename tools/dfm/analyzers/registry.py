"""Deterministic registry for production and injected DFM analyzers."""

from __future__ import annotations

from .base import Analyzer
from .drawing import DrawingAnalyzer
from .fusion import FusionAnalyzer
from .occt import OcctAnalyzer, discover_geometry_executable
from ..config import DFMConfig
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


def build_default_registry(config: DFMConfig | None = None) -> AnalyzerRegistry:
    config = config or DFMConfig()
    registry = AnalyzerRegistry()
    registry.register(
        OcctAnalyzer(
            discover_geometry_executable(config.geometry_executable),
            timeout_seconds=config.geometry_timeout_seconds,
        )
    )
    registry.register(DrawingAnalyzer())
    registry.register(FusionAnalyzer())
    return registry
