"""Versioned, JSON-compatible contracts shared by DFM services and tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from .errors import DFMError


MANIFEST_SCHEMA_VERSION = 1
WORKER_SCHEMA_VERSION = 1


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
    unit: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    version: str = "1"

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
    process: str = ""
    process_adapter_version: str = ""
    scope_id: str = ""
    scope_version: str = ""
    input_ids: list[str] = field(default_factory=list)
    input_hashes: dict[str, str] = field(default_factory=dict)
    rules: dict[str, "EffectiveRule"] = field(default_factory=dict)
    rule_bindings: list["RuleBinding"] = field(default_factory=list)
    operations: list["PlanOperation"] = field(default_factory=list)
    parent_plan_id: str | None = None
    invalidated_by: str | None = None
    affected_operation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "plan_id": self.plan_id,
            "input_mode": self.input_mode,
            "analyzer_keys": list(self.analyzer_keys),
            "status": self.status,
            "created_at": self.created_at,
            "process": self.process,
            "process_adapter_version": self.process_adapter_version,
            "scope_id": self.scope_id,
            "scope_version": self.scope_version,
            "input_ids": list(self.input_ids),
            "input_hashes": dict(self.input_hashes),
            "rules": {
                key: value.to_dict() for key, value in self.rules.items()
            },
            "rule_bindings": [item.to_dict() for item in self.rule_bindings],
            "operations": [operation.to_dict() for operation in self.operations],
            "parent_plan_id": self.parent_plan_id,
            "invalidated_by": self.invalidated_by,
            "affected_operation_ids": list(self.affected_operation_ids),
        }

    def validate(self) -> None:
        binding_ids = [item.binding_id for item in self.rule_bindings]
        if len(binding_ids) != len(set(binding_ids)):
            raise DFMError(
                "plan_rule_binding_invalid",
                "Plan rule binding IDs must be unique.",
            )
        operations = {item.operation_id: item for item in self.operations}
        for binding in self.rule_bindings:
            binding.validate()
            operation = operations.get(binding.operation_id)
            if (
                operation is None
                or binding.metric_id not in operation.metric_ids
                or binding.quantity_id not in operation.required_quantities
                or binding.rule_id not in self.rules
            ):
                raise DFMError(
                    "plan_rule_binding_invalid",
                    "A rule binding does not resolve within its plan.",
                    {"binding_id": binding.binding_id},
                )

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanRecord":
        values = dict(payload)
        values["rules"] = {
            key: EffectiveRule.from_dict(value)
            for key, value in values.get("rules", {}).items()
        }
        values["rule_bindings"] = [
            RuleBinding.from_dict(value)
            for value in values.get("rule_bindings", [])
        ]
        values["operations"] = [
            PlanOperation.from_dict(value) for value in values.get("operations", [])
        ]
        plan = cls(**values)
        plan.validate()
        return plan


@dataclass(frozen=True)
class EffectiveRule:
    value: Any
    unit: str | None
    source: str
    version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EffectiveRule":
        return cls(**payload)


@dataclass(frozen=True)
class RuleBinding:
    """Bind one objective quantity to a Hermes-owned engineering rule."""

    binding_id: str
    operation_id: str
    metric_id: str
    quantity_id: str
    rule_id: str
    operator: str
    aggregation: str

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RuleBinding":
        binding = cls(**payload)
        binding.validate()
        return binding

    def validate(self) -> None:
        identities = (
            self.binding_id,
            self.operation_id,
            self.metric_id,
            self.quantity_id,
            self.rule_id,
        )
        if any(not isinstance(value, str) or not value for value in identities):
            raise DFMError(
                "plan_rule_binding_invalid",
                "Rule bindings require non-empty stable identities.",
            )
        if self.operator not in {">=", "<=", ">", "<", "==", "!="}:
            raise DFMError(
                "plan_rule_binding_invalid",
                "Rule binding operator is unsupported.",
                {"binding_id": self.binding_id, "operator": self.operator},
            )
        if self.aggregation not in {
            "minimum",
            "maximum",
            "mean",
            "sum",
            "count",
            "identity",
        }:
            raise DFMError(
                "plan_rule_binding_invalid",
                "Rule binding aggregation is unsupported.",
                {"binding_id": self.binding_id, "aggregation": self.aggregation},
            )


@dataclass(frozen=True)
class PlanOperation:
    operation_id: str
    calculator_id: str
    depends_on: list[str] = field(default_factory=list)
    metric_ids: list[str] = field(default_factory=list)
    required_quantities: list[str] = field(default_factory=list)
    required_artifacts: list[str] = field(default_factory=list)
    arguments: dict[str, "ResolvedArgument"] = field(default_factory=dict)
    algorithm_options: dict[str, "ResolvedArgument"] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "operation_id": self.operation_id,
            "calculator_id": self.calculator_id,
            "depends_on": list(self.depends_on),
            "metric_ids": list(self.metric_ids),
            "required_quantities": list(self.required_quantities),
            "required_artifacts": list(self.required_artifacts),
            "arguments": {
                key: value.to_dict() for key, value in self.arguments.items()
            },
            "algorithm_options": {
                key: value.to_dict() for key, value in self.algorithm_options.items()
            },
        }

    def validate(self) -> None:
        if not self.operation_id or not self.calculator_id:
            raise DFMError(
                "plan_operation_invalid",
                "Plan operations require operation_id and calculator_id.",
            )
        if len(self.metric_ids) != len(set(self.metric_ids)):
            raise DFMError(
                "plan_operation_invalid",
                "Plan operation metric_ids must be unique.",
                {"operation_id": self.operation_id},
            )
        if len(self.required_quantities) != len(set(self.required_quantities)):
            raise DFMError(
                "plan_operation_invalid",
                "Plan operation required_quantities must be unique.",
                {"operation_id": self.operation_id},
            )
        if len(self.required_artifacts) != len(set(self.required_artifacts)):
            raise DFMError(
                "plan_operation_invalid",
                "Plan operation required_artifacts must be unique.",
                {"operation_id": self.operation_id},
            )
        for values in (self.arguments, self.algorithm_options):
            for name, argument in values.items():
                if not isinstance(name, str) or not name or not isinstance(
                    argument, ResolvedArgument
                ):
                    raise DFMError(
                        "plan_operation_invalid",
                        "Plan operation inputs must be named resolved arguments.",
                        {"operation_id": self.operation_id},
                    )
                argument.validate(name, self.operation_id)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PlanOperation":
        values = dict(payload)
        values["arguments"] = {
            key: ResolvedArgument.from_dict(value)
            for key, value in values.get("arguments", {}).items()
        }
        values["algorithm_options"] = {
            key: ResolvedArgument.from_dict(value)
            for key, value in values.get("algorithm_options", {}).items()
        }
        operation = cls(**values)
        operation.validate()
        return operation


@dataclass(frozen=True)
class ResolvedArgument:
    value: Any
    source_ref: str
    unit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ResolvedArgument":
        return cls(**payload)

    def validate(self, name: str, operation_id: str) -> None:
        if not self.source_ref:
            raise DFMError(
                "plan_operation_invalid",
                "Resolved operation arguments require source_ref provenance.",
                {"operation_id": operation_id, "argument": name},
            )


@dataclass(frozen=True)
class BoundingBox:
    minimum: list[float]
    maximum: list[float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BoundingBox":
        return cls(**payload)


@dataclass(frozen=True)
class RegionRecord:
    region_id: str
    input_sha256: str
    coordinate_system: str
    mode: str
    semantic_label: str
    source_refs: list[str]
    version: str
    content_sha256: str
    bbox: BoundingBox | None = None
    geometry_refs: list["GeometryRef"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "bbox": self.bbox.to_dict() if self.bbox else None,
            "geometry_refs": [item.to_dict() for item in self.geometry_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RegionRecord":
        values = dict(payload)
        if isinstance(values.get("bbox"), dict):
            values["bbox"] = BoundingBox.from_dict(values["bbox"])
        values["geometry_refs"] = [
            GeometryRef.from_dict(item) for item in values.get("geometry_refs", [])
        ]
        return cls(**values)


@dataclass(frozen=True)
class GeometryRef:
    """A topology reference valid for one immutable geometry input/version."""

    kind: str
    index: int
    input_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GeometryRef":
        return cls(**payload)


@dataclass(frozen=True)
class MeasurementRecord:
    """Deterministic geometry output, intentionally independent of a rule verdict."""

    measurement_id: str
    operation_id: str
    calculator_id: str
    metric_id: str
    quantity_id: str
    value: Any
    unit: str | None
    status: str
    geometry_refs: list[GeometryRef]
    method: str
    algorithm_version: str
    input_sha256: str
    quality: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    region_refs: list[str] = field(default_factory=list)
    field_refs: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "geometry_refs": [item.to_dict() for item in self.geometry_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MeasurementRecord":
        values = dict(payload)
        values["geometry_refs"] = [
            GeometryRef.from_dict(item) for item in values.get("geometry_refs", [])
        ]
        return cls(**values)


@dataclass(frozen=True)
class EvaluationRecord:
    """A versioned comparison between measurements and an effective parameter."""

    evaluation_id: str
    operation_id: str
    metric_id: str
    measurement_ids: list[str]
    rule_id: str
    rule_version: str
    rule_hash: str
    operator: str
    expected: Any
    actual: Any
    outcome: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvaluationRecord":
        return cls(**payload)


@dataclass(frozen=True)
class EvidenceRecord:
    """Bind one Hermes-rendered image to the exact evaluated geometry."""

    evidence_id: str
    run_id: str
    input_sha256: str
    operation_id: str
    metric_id: str
    measurement_ids: list[str]
    evaluation_ids: list[str]
    geometry_refs: list[GeometryRef]
    region_refs: list[str]
    artifact_ref: str
    render: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "geometry_refs": [item.to_dict() for item in self.geometry_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EvidenceRecord":
        values = dict(payload)
        values["geometry_refs"] = [
            GeometryRef.from_dict(item) for item in values.get("geometry_refs", [])
        ]
        return cls(**values)


@dataclass(frozen=True)
class WorkerRequest:
    schema_version: int
    run_id: str
    input_path: str
    output_dir: str
    process: str
    scope_id: str
    analyzer_version: str
    rules: dict[str, EffectiveRule] = field(default_factory=dict)
    operations: list[PlanOperation] = field(default_factory=list)
    max_evidence_findings: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "rules": {
                key: value.to_dict() for key, value in self.rules.items()
            },
            "operations": [operation.to_dict() for operation in self.operations],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerRequest":
        values = dict(payload)
        values["rules"] = {
            key: EffectiveRule.from_dict(value)
            for key, value in values.get("rules", {}).items()
        }
        values["operations"] = [
            PlanOperation.from_dict(value) for value in values.get("operations", [])
        ]
        return cls(**values)


@dataclass(frozen=True)
class WorkerEvent:
    schema_version: int
    type: str
    stage: str | None = None
    percent: int | None = None
    kind: str | None = None
    path: str | None = None
    code: str | None = None
    message: str | None = None
    external_job_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerEvent":
        try:
            event = cls(**payload)
        except (TypeError, ValueError) as exc:
            raise DFMError(
                "worker_event_invalid", "DFM worker event is invalid."
            ) from exc
        if event.schema_version != WORKER_SCHEMA_VERSION:
            raise DFMError(
                "worker_event_invalid",
                "DFM worker event schema version is unsupported.",
                {"schema_version": event.schema_version},
            )
        if event.type not in {"progress", "artifact", "completed", "error"}:
            raise DFMError(
                "worker_event_invalid",
                "DFM worker event type is unsupported.",
                {"type": event.type},
            )
        if event.type == "progress" and (
            event.percent is None or not 0 <= event.percent <= 100
        ):
            raise DFMError(
                "worker_event_invalid",
                "DFM worker progress percent must be between 0 and 100.",
            )
        return event


@dataclass(frozen=True)
class WorkerResult:
    schema_version: int
    worker_version: str
    input_sha256: str
    process: str
    scope_id: str
    rules: dict[str, EffectiveRule]
    result_path: str
    artifacts: list[dict[str, str]] = field(default_factory=list)
    measurement_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "rules": {
                key: value.to_dict() for key, value in self.rules.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkerResult":
        values = dict(payload)
        values["rules"] = {
            key: EffectiveRule.from_dict(value)
            for key, value in values.get("rules", {}).items()
        }
        return cls(**values)


@dataclass(frozen=True)
class FindingRecord:
    finding_id: str
    title: str
    severity: str
    status: str
    evaluation_ids: list[str]
    measurement_ids: list[str]
    metric_ids: list[str]
    region_refs: list[str]
    evidence_refs: list[str]
    rule_refs: list[str]
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
    preflight: dict[str, Any] = field(default_factory=dict)
    supersedes_input_id: str | None = None
    format_id: str = ""
    representation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_id": self.input_id,
            "kind": self.kind,
            "source_name": self.source_name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "preflight": dict(self.preflight),
            "supersedes_input_id": self.supersedes_input_id,
            "format_id": self.format_id,
            "representation": self.representation,
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
    plan_id: str | None = None
    plan_snapshot: dict[str, Any] | None = None
    stage: str | None = None
    progress_percent: int = 0
    heartbeat_at: str | None = None
    event_log_path: str | None = None
    worker_stdout_path: str | None = None
    worker_stderr_path: str | None = None
    external_job_id: str | None = None

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
            "plan_id": self.plan_id,
            "plan_snapshot": self.plan_snapshot,
            "stage": self.stage,
            "progress_percent": self.progress_percent,
            "heartbeat_at": self.heartbeat_at,
            "event_log_path": self.event_log_path,
            "worker_stdout_path": self.worker_stdout_path,
            "worker_stderr_path": self.worker_stderr_path,
            "external_job_id": self.external_job_id,
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
    process: str = "injection"
    process_source: str = "default"
    input_mode: str | None = None
    inputs: list[InputRecord] = field(default_factory=list)
    facts: list[FactRecord] = field(default_factory=list)
    regions: list[RegionRecord] = field(default_factory=list)
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
            "process": self.process,
            "process_source": self.process_source,
            "input_mode": self.input_mode,
            "revision": self.revision,
            "idempotency_key": self.idempotency_key,
            "inputs": [item.to_dict() for item in self.inputs],
            "facts": [item.to_dict() for item in self.facts],
            "regions": [item.to_dict() for item in self.regions],
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
        values["facts"] = [
            FactRecord.from_dict(item) for item in values.get("facts", [])
        ]
        values["regions"] = [
            RegionRecord.from_dict(item) for item in values.get("regions", [])
        ]
        values["clarifications"] = [
            ClarificationRecord.from_dict(item)
            for item in values.get("clarifications", [])
        ]
        values["features"] = [
            FeatureRecord.from_dict(item) for item in values.get("features", [])
        ]
        values["plans"] = [
            PlanRecord.from_dict(item) for item in values.get("plans", [])
        ]
        values["runs"] = [RunRecord.from_dict(item) for item in values.get("runs", [])]
        values["findings"] = [
            FindingRecord.from_dict(item) for item in values.get("findings", [])
        ]
        values["artifacts"] = [
            ArtifactRecord.from_dict(item) for item in values.get("artifacts", [])
        ]
        return cls(**values)
