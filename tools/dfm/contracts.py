"""Versioned, JSON-compatible contracts shared by DFM services and tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .errors import DFMError


MANIFEST_SCHEMA_VERSION = 1


class CapabilityStatus(str, Enum):
    AVAILABLE = "available"
    DEPENDENCY_MISSING = "dependency_missing"
    NOT_IMPLEMENTED = "not_implemented"
    DISABLED = "disabled"
    UNHEALTHY = "unhealthy"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


_RUN_TRANSITIONS = {
    RunStatus.QUEUED: {
        RunStatus.RUNNING,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BLOCKED,
    },
    RunStatus.RUNNING: {
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.BLOCKED,
    },
}


def ensure_run_transition(current: RunStatus, target: RunStatus) -> None:
    """Raise when a persisted run attempts an invalid state transition."""

    if target not in _RUN_TRANSITIONS.get(current, set()):
        raise DFMError(
            "invalid_run_transition",
            f"Cannot transition DFM run from {current.value} to {target.value}.",
            {"current": current.value, "target": target.value},
        )


@dataclass(frozen=True)
class Capability:
    analyzer_key: str
    status: CapabilityStatus
    reason: str
    error_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer_key": self.analyzer_key,
            "status": self.status.value,
            "reason": self.reason,
            "error_code": self.error_code,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class FactRecord:
    fact_id: str
    name: str
    value: Any
    source: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactRecord":
        return cls(**payload)


@dataclass(frozen=True)
class ClarificationRecord:
    clarification_id: str
    question: str
    status: str
    answer: Any | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClarificationRecord":
        return cls(**payload)


@dataclass(frozen=True)
class FeatureRecord:
    feature_id: str
    kind: str
    source_refs: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FeatureRecord":
        return cls(**payload)


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    input_mode: str
    analyzer_keys: list[str]
    status: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanRecord":
        return cls(**payload)


@dataclass(frozen=True)
class FindingRecord:
    finding_id: str
    title: str
    severity: str
    status: str
    evidence_refs: list[str]
    rule_ref: str
    recommendation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FindingRecord":
        return cls(**payload)


@dataclass(frozen=True)
class InputRecord:
    input_id: str
    kind: str
    source_name: str
    relative_path: str
    size_bytes: int
    sha256: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "kind": self.kind,
            "source_name": self.source_name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "InputRecord":
        return cls(**payload)


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    kind: str
    relative_path: str
    media_type: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "relative_path": self.relative_path,
            "media_type": self.media_type,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ArtifactRecord":
        return cls(**payload)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    analyzer_key: str
    analyzer_version: str
    status: RunStatus
    created_at: str
    updated_at: str
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    error: dict[str, Any] | None = None
    idempotency_key: str | None = None
    owner_pid: int | None = None
    runtime_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "analyzer_key": self.analyzer_key,
            "analyzer_version": self.analyzer_version,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "error": self.error,
            "idempotency_key": self.idempotency_key,
            "owner_pid": self.owner_pid,
            "runtime_id": self.runtime_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunRecord":
        values = dict(payload)
        values["status"] = RunStatus(values["status"])
        values["artifacts"] = [
            ArtifactRecord.from_dict(item) for item in values.get("artifacts", [])
        ]
        return cls(**values)


@dataclass(frozen=True)
class ProjectManifest:
    project_id: str
    name: str
    created_at: str
    updated_at: str
    domain: str = "injection_molding"
    input_mode: str | None = None
    inputs: list[InputRecord] = field(default_factory=list)
    facts: list[FactRecord] = field(default_factory=list)
    clarifications: list[ClarificationRecord] = field(default_factory=list)
    features: list[FeatureRecord] = field(default_factory=list)
    plans: list[PlanRecord] = field(default_factory=list)
    runs: list[RunRecord] = field(default_factory=list)
    findings: list[FindingRecord] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    capabilities: dict[str, dict[str, Any]] = field(default_factory=dict)
    schema_version: int = MANIFEST_SCHEMA_VERSION
    revision: int = 0
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "domain": self.domain,
            "input_mode": self.input_mode,
            "revision": self.revision,
            "idempotency_key": self.idempotency_key,
            "inputs": [item.to_dict() for item in self.inputs],
            "facts": [item.to_dict() for item in self.facts],
            "clarifications": [item.to_dict() for item in self.clarifications],
            "features": [item.to_dict() for item in self.features],
            "plans": [item.to_dict() for item in self.plans],
            "runs": [run.to_dict() for run in self.runs],
            "findings": [item.to_dict() for item in self.findings],
            "artifacts": [item.to_dict() for item in self.artifacts],
            "capabilities": self.capabilities,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectManifest":
        values = dict(payload)
        values["inputs"] = [
            InputRecord.from_dict(item) for item in values.get("inputs", [])
        ]
        values["facts"] = [FactRecord.from_dict(item) for item in values.get("facts", [])]
        values["clarifications"] = [
            ClarificationRecord.from_dict(item)
            for item in values.get("clarifications", [])
        ]
        values["features"] = [
            FeatureRecord.from_dict(item) for item in values.get("features", [])
        ]
        values["plans"] = [PlanRecord.from_dict(item) for item in values.get("plans", [])]
        values["runs"] = [RunRecord.from_dict(item) for item in values.get("runs", [])]
        values["findings"] = [
            FindingRecord.from_dict(item) for item in values.get("findings", [])
        ]
        values["artifacts"] = [
            ArtifactRecord.from_dict(item) for item in values.get("artifacts", [])
        ]
        return cls(**values)
