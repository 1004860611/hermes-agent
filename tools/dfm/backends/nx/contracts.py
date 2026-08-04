"""Versioned, JSON-only contracts for the external NX compute service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


NX_API_VERSION = "v1"
NX_REQUEST_SCHEMA_VERSION = 1
NX_TASK_REQUEST_SCHEMA_VERSION = 2


@dataclass(frozen=True)
class NXCalculatorCapability:
    status: str
    contract_version: int = 1
    implementation_version: str = ""
    required_arguments: tuple[str, ...] = ()
    optional_arguments: tuple[str, ...] = ()
    output_quantities: tuple[str, ...] = ()
    certification_scope: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "NXCalculatorCapability":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(status=value)
        if not isinstance(value, dict):
            return cls(status="not_implemented")
        try:
            contract_version = int(value.get("contract_version") or 1)
        except (TypeError, ValueError):
            contract_version = 0

        def _strings(key: str) -> tuple[str, ...]:
            items = value.get(key)
            if not isinstance(items, list):
                return ()
            return tuple(str(item) for item in items)

        scope = value.get("certification_scope")
        return cls(
            status=str(value.get("status") or "not_implemented"),
            contract_version=contract_version,
            implementation_version=str(value.get("implementation_version") or ""),
            required_arguments=_strings("required_arguments"),
            optional_arguments=_strings("optional_arguments"),
            output_quantities=_strings("output_quantities"),
            certification_scope=dict(scope) if isinstance(scope, dict) else {},
        )


@dataclass(frozen=True)
class NXCapability:
    status: str
    backend_version: str = ""
    plugin_version: str = ""
    formats: dict[str, str] = field(default_factory=dict)
    calculators: dict[str, str | dict[str, Any]] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NXCapability":
        return cls(
            status=str(payload.get("status") or "unhealthy"),
            backend_version=str(payload.get("backend_version") or ""),
            plugin_version=str(payload.get("plugin_version") or ""),
            formats=dict(payload.get("formats") or {}),
            calculators=dict(payload.get("calculators") or {}),
            details=dict(payload.get("details") or {}),
        )

    def calculator(self, calculator_id: str) -> NXCalculatorCapability:
        return NXCalculatorCapability.from_value(self.calculators.get(calculator_id))


@dataclass(frozen=True)
class NXJobStatus:
    job_id: str
    status: str
    stage: str = ""
    progress_percent: int = 0
    error: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NXJobStatus":
        return cls(
            job_id=str(payload.get("job_id") or ""),
            status=str(payload.get("status") or ""),
            stage=str(payload.get("stage") or ""),
            progress_percent=int(payload.get("progress_percent") or 0),
            error=dict(payload["error"])
            if isinstance(payload.get("error"), dict)
            else None,
        )


@dataclass(frozen=True)
class NXArtifact:
    artifact_id: str
    kind: str
    filename: str
    media_type: str
    sha256: str
    size_bytes: int

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NXArtifact":
        return cls(
            artifact_id=str(payload.get("artifact_id") or ""),
            kind=str(payload.get("kind") or "artifact"),
            filename=str(payload.get("filename") or ""),
            media_type=str(payload.get("media_type") or "application/octet-stream"),
            sha256=str(payload.get("sha256") or ""),
            size_bytes=int(payload.get("size_bytes") or 0),
        )
