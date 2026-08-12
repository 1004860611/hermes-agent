"""Provider contract for concrete semantic feature recognizers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ..contracts import FeatureRecord, InputRecord, RegionRecord


@dataclass(frozen=True)
class FeatureRecognitionResult:
    features: list[FeatureRecord]
    regions: list[RegionRecord]
    diagnostics: dict[str, Any]


@runtime_checkable
class FeatureRecognitionProvider(Protocol):
    key: str
    version: str

    def capability(self) -> dict[str, Any]: ...

    def recognize(
        self, input_record: InputRecord, *, process: str
    ) -> FeatureRecognitionResult: ...
