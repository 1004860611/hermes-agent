"""Parasolid analysis through the configured remote Siemens NX service."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import time
from pathlib import Path

from ..backends.nx.client import NXBackendClient
from ..backends.nx.contracts import (
    NX_REQUEST_SCHEMA_VERSION,
    NX_TASK_REQUEST_SCHEMA_VERSION,
)
from ..contracts import (
    ArtifactRecord,
    Capability,
    CapabilityStatus,
    PlanOperation,
    WorkerEvent,
)
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ParasolidAnalyzer:
    key = "parasolid"
    version = "nx-http-v1"
    supported_inputs = ("parasolid", "geometry", "fusion")

    def __init__(
        self,
        client: NXBackendClient | None = None,
        *,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        self.client = client
        self.poll_interval_seconds = poll_interval_seconds

    def capability(self, context: AnalyzerContext) -> Capability:
        if self.client is None:
            return Capability(
                self.key,
                CapabilityStatus.DEPENDENCY_MISSING,
                "NX HTTP backend is not configured.",
                "dependency_missing",
                {"config": "dfm.nx.endpoint", "transport": "http"},
            )
        try:
            remote = self.client.capability()
        except DFMError as exc:
            return Capability(
                self.key,
                CapabilityStatus.UNHEALTHY,
                exc.message,
                exc.code,
                exc.details or {},
            )
        format_status = remote.formats.get("parasolid_xt", "not_implemented")
        if remote.status != "available" or format_status != "available":
            return Capability(
                self.key,
                CapabilityStatus.NOT_IMPLEMENTED
                if format_status == "not_implemented"
                else CapabilityStatus.UNHEALTHY,
                "NX backend does not currently provide certified Parasolid XT loading.",
                "unsupported_capability",
                {
                    "remote_status": remote.status,
                    "format_status": format_status,
                    "backend_version": remote.backend_version,
                },
            )
        if context.plan is not None:
            required = [
                item
                for item in context.plan.operations
                if item.operation not in {"load_step", "render_evidence"}
            ]
            uncertified = sorted({
                operation.operation
                for operation in required
                if remote.calculator(operation.operation).status != "certified"
            })
            if uncertified:
                return Capability(
                    self.key,
                    CapabilityStatus.NOT_IMPLEMENTED,
                    "NX backend does not certify every calculator required by this plan.",
                    "unsupported_capability",
                    {
                        "uncertified_operations": uncertified,
                        "calculator_statuses": remote.calculators,
                    },
                )
            incompatible = []
            for operation in required:
                if not operation.uses_task_contract_v2:
                    continue
                calculator_id = operation.operation
                definition = remote.calculator(calculator_id)
                supplied = set(operation.arguments)
                required_arguments = set(definition.required_arguments)
                supported_arguments = required_arguments | set(
                    definition.optional_arguments
                )
                reasons = []
                if definition.contract_version < NX_TASK_REQUEST_SCHEMA_VERSION:
                    reasons.append("contract_version")
                if not required_arguments.issubset(supplied):
                    reasons.append("required_arguments")
                if supplied - supported_arguments:
                    reasons.append("unsupported_arguments")
                if reasons:
                    incompatible.append({
                        "operation_id": operation.operation_id,
                        "calculator_id": calculator_id,
                        "reasons": reasons,
                    })
            if incompatible:
                return Capability(
                    self.key,
                    CapabilityStatus.NOT_IMPLEMENTED,
                    "NX backend does not certify the task contract required by this plan.",
                    "unsupported_capability",
                    {"incompatible_operation_contracts": incompatible},
                )
        return Capability(
            self.key,
            CapabilityStatus.AVAILABLE,
            "The remote NX Parasolid analyzer is available.",
            details={
                "transport": "http",
                "backend_version": remote.backend_version,
                "plugin_version": remote.plugin_version,
                "calculators": remote.calculators,
                "format_id": "parasolid_xt",
                "representation": "brep",
            },
        )

    def run(
        self, context: AnalyzerContext, cancellation: CancellationToken
    ) -> list[ArtifactRecord]:
        cancellation.raise_if_cancelled()
        if self.client is None or context.plan is None:
            raise DFMError(
                "plan_required",
                "A configured NX backend and persisted plan are required.",
            )
        capability = self.capability(context)
        if capability.status is not CapabilityStatus.AVAILABLE:
            raise DFMError(
                capability.error_code or capability.status.value,
                capability.reason,
                capability.details,
            )
        input_record = next(
            (
                item
                for item in context.inputs
                if item.input_id in context.plan.input_ids
                and item.format_id == "parasolid_xt"
            ),
            None,
        )
        if input_record is None:
            raise DFMError(
                "input_required",
                "The DFM plan does not reference a Parasolid x_t input.",
            )
        input_path = (context.project_dir / input_record.relative_path).resolve()
        request_schema_version = (
            NX_TASK_REQUEST_SCHEMA_VERSION
            if any(item.uses_task_contract_v2 for item in context.plan.operations)
            else NX_REQUEST_SCHEMA_VERSION
        )
        request = {
            "schema_version": request_schema_version,
            "run_id": context.run_id,
            "process": context.plan.process,
            "scope_id": context.plan.scope_id,
            "scope_version": context.plan.scope_version,
            "operations": [
                item.to_nx_dict(request_schema_version)
                for item in context.plan.operations
            ],
            "parameters": {
                key: value.to_dict() for key, value in context.plan.parameters.items()
            },
        }
        job = self.client.submit(request, input_path)
        if not job.job_id:
            raise DFMError("nx_protocol_invalid", "NX backend did not return a job_id.")
        self._emit(context, job.stage or "nx_queued", job.progress_percent, job.job_id)
        while job.status not in {"succeeded", "failed", "cancelled"}:
            if cancellation.is_cancelled:
                self.client.cancel(job.job_id)
                cancellation.raise_if_cancelled()
            self._emit(
                context, job.stage or "nx_remote", job.progress_percent, job.job_id
            )
            time.sleep(self.poll_interval_seconds)
            job = self.client.status(job.job_id)
        if job.status != "succeeded":
            error = job.error or {}
            raise DFMError(
                str(error.get("code") or "nx_analysis_failed"),
                str(error.get("message") or f"NX job ended with status {job.status}."),
                {"nx_job_id": job.job_id},
            )

        output_dir = context.project_dir / "runs" / context.run_id / "artifacts"
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ArtifactRecord] = []
        for index, remote in enumerate(self.client.artifacts(job.job_id), start=1):
            filename = Path(remote.filename).name
            if not filename or filename != remote.filename or remote.size_bytes < 0:
                raise DFMError(
                    "nx_artifact_invalid",
                    "NX backend returned an unsafe artifact filename.",
                )
            target = output_dir / filename
            temporary = output_dir / f".{filename}.part"
            try:
                with temporary.open("wb") as handle:
                    self.client.download(job.job_id, remote, handle)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            artifacts.append(
                ArtifactRecord(
                    f"artifact_{context.run_id}_{index}",
                    remote.kind,
                    target.relative_to(context.project_dir).as_posix(),
                    remote.media_type,
                    _utc_now(),
                )
            )
        if not any(item.kind == "measurements" for item in artifacts):
            raise DFMError(
                "nx_result_invalid",
                "NX backend result must include a measurements artifact.",
            )
        if request_schema_version >= NX_TASK_REQUEST_SCHEMA_VERSION:
            measurements = next(
                item for item in artifacts if item.kind == "measurements"
            )
            self._validate_task_measurements(
                context.plan.operations,
                context.project_dir / measurements.relative_path,
            )
        self._emit(context, "complete", 100, job.job_id)
        return artifacts

    @staticmethod
    def _validate_task_measurements(
        operations: list[PlanOperation],
        path: Path,
    ) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DFMError(
                "nx_result_invalid",
                "NX task measurements artifact is not valid JSON.",
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != NX_TASK_REQUEST_SCHEMA_VERSION
            or payload.get("producer_contract") != "measurement_only"
            or not isinstance(payload.get("measurements"), list)
        ):
            raise DFMError(
                "nx_result_invalid",
                "NX task measurements artifact does not implement Measurement contract v2.",
            )

        task_operations = {
            operation.operation_id: operation
            for operation in operations
            if operation.uses_task_contract_v2
        }
        expected = {
            (operation.operation_id, metric_id)
            for operation in task_operations.values()
            for metric_id in operation.metric_refs
        }
        received = set()
        for measurement in payload["measurements"]:
            if not isinstance(measurement, dict):
                raise DFMError(
                    "nx_result_invalid",
                    "NX task measurements must contain JSON objects.",
                )
            operation_ref = str(measurement.get("operation_ref") or "")
            if not operation_ref:
                continue  # v1/topology records may coexist in a v2 artifact.
            operation = task_operations.get(operation_ref)
            metric_id = str(measurement.get("metric_id") or "")
            if (
                operation is None
                or measurement.get("check_id") != operation_ref
                or measurement.get("calculator_id") != operation.operation
                or metric_id not in operation.metric_refs
            ):
                raise DFMError(
                    "nx_result_invalid",
                    "NX Measurement does not link to the submitted task contract.",
                    {"measurement_id": measurement.get("measurement_id")},
                )
            received.add((operation_ref, metric_id))
        missing = sorted(expected - received)
        if missing:
            raise DFMError(
                "nx_result_invalid",
                "NX task measurements are missing required metric results.",
                {"missing_operation_metrics": missing},
            )

    @staticmethod
    def _emit(
        context: AnalyzerContext, stage: str, percent: int, job_id: str = ""
    ) -> None:
        if context.event_sink is not None:
            context.event_sink(
                WorkerEvent(
                    1,
                    "progress",
                    stage=stage,
                    percent=max(0, min(100, int(percent))),
                    external_job_id=job_id or None,
                )
            )
