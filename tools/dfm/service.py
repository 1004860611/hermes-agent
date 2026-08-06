"""Application service behind the stable Hermes DFM tool schemas."""

from __future__ import annotations

import os
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.context_references import parse_context_references
from hermes_constants import get_hermes_home

from .analyzers.base import AnalyzerContext
from .analyzers.registry import AnalyzerRegistry, build_default_registry
from .config import DFMConfig, load_dfm_config
from .contracts import (
    ClarificationRecord,
    FactRecord,
    PlanRecord,
    ProjectManifest,
    RunRecord,
    RunStatus,
)
from .errors import DFMError
from .project.inputs import InputRegistrar
from .project.manifest import ManifestStore
from .project.workspace import DFMWorkspace
from .processes.registry import ProcessAdapterRegistry, build_default_process_registry
from .runtime.jobs import JobManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _resolve_input_path(raw_path: object, working_dir: object = None) -> Path:
    value = str(raw_path or "").strip()
    references = parse_context_references(value)
    if len(references) == 1 and references[0].kind == "file" and references[0].raw == value:
        value = references[0].target
    elif len(value) >= 2 and value[0] == value[-1] and value[0] in "`\"'":
        value = value[1:-1]

    path = Path(os.path.expanduser(value))
    if not path.is_absolute() and working_dir:
        path = Path(str(working_dir)).expanduser() / path
    return path.resolve()


class DFMService:
    _FACTS_REQUIRING_NORMALIZATION = {"pull_dir"}
    _FACT_ALIASES = {
        "unit": "model_units",
        "units": "model_units",
        "model_unit": "model_units",
        "model_units": "model_units",
        "pull_direction": "pull_dir",
        "mold_pull_direction": "pull_dir",
        "pull_dir": "pull_dir",
        "material": "material",
    }
    
    def __init__(self, *, config: DFMConfig | None = None, workspace: DFMWorkspace | None = None, registry: AnalyzerRegistry | None = None, process_registry: ProcessAdapterRegistry | None = None, reconcile_jobs: bool = True) -> None:
        self.config = config or load_dfm_config()
        self.workspace = workspace or DFMWorkspace()
        self.registry = registry or build_default_registry(self.config)
        self.process_registry = process_registry or build_default_process_registry()
        self.inputs = InputRegistrar(self.workspace, self.config)
        self.jobs = JobManager(self.workspace, self.registry, self.config, reconcile=reconcile_jobs)

    def _store(self, project_id: str) -> ManifestStore:
        return ManifestStore(self.workspace.project_dir(project_id))

    def _context(
        self, manifest: ProjectManifest, plan: PlanRecord | None = None
    ) -> AnalyzerContext:
        return AnalyzerContext(
            manifest.project_id,
            self.workspace.project_dir(manifest.project_id),
            manifest.input_mode,
            manifest.inputs,
            plan=plan,
        )

    @staticmethod
    def _canonical_fact_name(fact_name: str) -> str:
        normalized = str(fact_name or "").strip().lower().replace("-", "_").replace(" ", "_")
        return DFMService._FACT_ALIASES.get(normalized, normalized)

    @staticmethod
    def _normalize_fact_value(fact_name: str, raw_value: Any) -> Any:
        """Normalize fact values that may be serialized as JSON strings.
        
        Some facts (like pull_dir) require array values, but tool parameters
        are JSON-serialized. This method parses them back to proper types.
        
        Args:
            fact_name: The name of the fact being confirmed.
            raw_value: The raw value from the tool call (may be a JSON string).
            
        Returns:
            The normalized value (parsed if necessary).
        """
        if fact_name not in DFMService._FACTS_REQUIRING_NORMALIZATION:
            return raw_value
            
        # If already a list/tuple, return as-is
        if isinstance(raw_value, (list, tuple)):
            return raw_value
            
        # If a string, try to parse as JSON
        if isinstance(raw_value, str):
            try:
                import json
                parsed = json.loads(raw_value)
                if isinstance(parsed, list):
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
                
        return raw_value

    @staticmethod
    def _active_inputs(manifest: ProjectManifest):
        superseded = {item.supersedes_input_id for item in manifest.inputs if item.supersedes_input_id}
        return [item for item in manifest.inputs if item.input_id not in superseded]

    @staticmethod
    def _operation_closure(operations, affected_ids: list[str]):
        if not affected_ids:
            return list(operations)
        by_id = {item.operation_id: item for item in operations}
        required = set()

        def include(operation_id: str) -> None:
            if operation_id in required or operation_id not in by_id:
                return
            required.add(operation_id)
            for dependency in by_id[operation_id].depends_on:
                include(dependency)

        for operation_id in affected_ids:
            include(operation_id)
        return [item for item in operations if item.operation_id in required]

    def _capabilities(self, manifest: ProjectManifest) -> dict[str, dict[str, Any]]:
        context = self._context(manifest)
        return {key: self.registry.get(key).capability(context).to_dict() for key in self.registry.keys()}

    def _open_clarifications(
        self, manifest: ProjectManifest, process: str | None = None
    ) -> list[ClarificationRecord]:
        # Reserved Parasolid-only projects do not ask engineering questions
        # before an approved reader exists. Mixed/STEP geometry still uses the
        # selected process adapter's prerequisites.
        if manifest.input_mode not in {"step", "geometry", "fusion"} and not (
            manifest.input_mode == "parasolid" and self.config.nx_endpoint
        ):
            return []
        adapter = self.process_registry.get(process or manifest.process or self.config.default_process)
        required_facts = adapter.required_facts()
        confirmed = {
            self._canonical_fact_name(fact.name)
            for fact in manifest.facts
            if fact.status == "confirmed"
        }
        existing = {item.clarification_id: item for item in manifest.clarifications}
        result = []
        for name, question in required_facts.items():
            if name in confirmed:
                continue
            clarification_id = f"clarification_{name}"
            item = existing.get(clarification_id)
            if item is None or item.status == "open":
                result.append(item or ClarificationRecord(clarification_id, question, "open"))
        return result

    def _reconcile_clarifications(self, project_id: str) -> ProjectManifest:
        """Close old open clarification rows when an alias fact already exists."""
        store = self._store(project_id)

        def reconcile(current: ProjectManifest) -> ProjectManifest:
            confirmed = {
                self._canonical_fact_name(fact.name): fact
                for fact in current.facts
                if fact.status == "confirmed"
            }
            changed = False
            rows = []
            for item in current.clarifications:
                canonical = self._canonical_fact_name(
                    item.clarification_id.removeprefix("clarification_")
                )
                fact = confirmed.get(canonical)
                if fact is not None and item.status != "answered":
                    item = replace(item, status="answered", answer=fact.value)
                    changed = True
                rows.append(item)
            return replace(current, clarifications=rows) if changed else current

        return store.update(reconcile)

    def _ensure_clarifications(self, project_id: str) -> ProjectManifest:
        store = self._store(project_id)

        def ensure(current: ProjectManifest) -> ProjectManifest:
            pending = self._open_clarifications(current)
            known = {item.clarification_id for item in current.clarifications}
            additions = [item for item in pending if item.clarification_id not in known]
            if not additions:
                return current
            return replace(
                current,
                clarifications=[*current.clarifications, *additions],
                updated_at=_utc_now(),
            )

        return store.update(ensure)

    def _project_payload(self, manifest: ProjectManifest) -> dict[str, Any]:
        payload = manifest.to_dict()
        payload["open_clarifications"] = [item.to_dict() for item in self._open_clarifications(manifest)]
        return payload

    def _select_process(self, project_id: str, process: str, source: str) -> ProjectManifest:
        self.process_registry.get(process)
        return self._store(project_id).update(
            lambda current: current
            if current.process == process and current.process_source == source
            else replace(
                current,
                process=process,
                process_source=source,
                domain=(
                    "injection_molding"
                    if process == "injection"
                    else "die_casting"
                    if process == "die_casting"
                    else process
                ),
                plans=[
                    replace(
                        plan,
                        status="invalidated",
                        invalidated_by=f"process:{process}",
                        affected_operation_ids=[item.operation_id for item in plan.operations],
                    )
                    for plan in current.plans
                ],
                updated_at=_utc_now(),
            )
        )

    @staticmethod
    def _resolve_run_id(manifest: ProjectManifest, requested: object, action: str) -> str:
        """Recover an omitted run id without guessing across concurrent runs."""
        run_id = str(requested or "").strip()
        if run_id:
            return run_id
        if len(manifest.runs) == 1:
            return manifest.runs[0].run_id
        active = [
            run
            for run in manifest.runs
            if run.status in {RunStatus.QUEUED, RunStatus.RUNNING}
        ]
        if len(active) == 1:
            return active[0].run_id
        raise DFMError(
            "run_id_required",
            f"dfm_analysis {action} requires run_id when this project has multiple runs.",
            {
                "action": action,
                "run_ids": [run.run_id for run in manifest.runs[-5:]],
            },
        )

    def project(self, action: str, **params: Any) -> dict[str, Any]:
        if action == "create":
            manifest = self.workspace.create_project(params.get("name") or "Untitled DFM project", params.get("idempotency_key"))
            return {"ok": True, "project_id": manifest.project_id, "project": manifest.to_dict()}
        if action == "list":
            projects = []
            if self.workspace.projects_dir.exists():
                for path in sorted(self.workspace.projects_dir.glob("dfm_*/project_manifest.json")):
                    try:
                        projects.append(ManifestStore(path.parent).load().to_dict())
                    except DFMError:
                        continue
            return {"ok": True, "projects": projects}

        project_id = params.get("project_id") or ""
        if action == "add_input":
            source_path = _resolve_input_path(params.get("path"), params.get("working_dir"))
            record = self.inputs.register(project_id, source_path)
            manifest = self._ensure_clarifications(project_id)
            return {
                "ok": True,
                "project_id": project_id,
                "input": record.to_dict(),
                "open_clarifications": [item.to_dict() for item in self._open_clarifications(manifest)],
            }
        if action == "confirm_fact":
            name = self._canonical_fact_name(str(params.get("fact_name") or ""))
            if not name:
                raise DFMError("fact_invalid", "fact_name is required.")
            
            # Normalize fact_value: parse JSON strings for known array parameters
            raw_value = params.get("fact_value")
            normalized_value = self._normalize_fact_value(name, raw_value)
            
            fact = FactRecord(f"fact_{uuid4().hex[:16]}", name, normalized_value, "user", "confirmed")
            manifest = self._store(project_id).update(
                lambda current: replace(
                    current,
                    facts=[*current.facts, fact],
                    clarifications=[
                        replace(item, status="answered", answer=fact.value)
                        if item.clarification_id == f"clarification_{name}"
                        else item
                        for item in current.clarifications
                    ],
                    plans=[
                        replace(
                            plan,
                            status="invalidated",
                            invalidated_by=f"fact:{name}",
                            affected_operation_ids=(
                                ["geometry.draft", "geometry.undercut"]
                                if name == "pull_dir"
                                else [item.operation_id for item in plan.operations]
                            ),
                        )
                        for plan in current.plans
                    ],
                    updated_at=_utc_now(),
                )
            )
            return {"ok": True, "project_id": project_id, "fact": fact.to_dict(), "revision": manifest.revision}
        if action == "status":
            manifest = self._reconcile_clarifications(project_id)
            context = self._context(manifest)
            process_capabilities = {
                key: self.process_registry.get(key).capability(context).to_dict()
                for key in self.process_registry.keys()
            }
            return {
                "ok": True,
                "project": self._project_payload(manifest),
                "capabilities": self._capabilities(manifest),
                "process_capabilities": process_capabilities,
            }
        raise DFMError("action_invalid", f"Unsupported dfm_project action: {action}")

    def analysis(self, action: str, **params: Any) -> dict[str, Any]:
        project_id = params.get("project_id") or ""
        if action == "plan":
            store = self._store(project_id)
            manifest = self._reconcile_clarifications(project_id)
            analyzer_key = params.get("analyzer_key") or manifest.input_mode
            if not analyzer_key:
                raise DFMError("input_required", "Register a DFM input before planning analysis.")
            requested_process = str(params.get("process") or manifest.process or self.config.default_process)
            manifest = self._select_process(
                project_id,
                requested_process,
                "user_selected" if params.get("process") else manifest.process_source,
            )
            manifest = self._ensure_clarifications(project_id)
            open_clarifications = self._open_clarifications(manifest, requested_process)
            if open_clarifications:
                return {
                    "ok": False,
                    "project_id": project_id,
                    "status": "clarification_required",
                    "requires_user_response": True,
                    "next_action": "clarify",
                    "do_not_infer": True,
                    "clarifications": [item.to_dict() for item in open_clarifications],
                }
            analyzer = self.registry.get(str(analyzer_key))
            context = self._context(manifest)
            capability = analyzer.capability(context)
            process = requested_process
            process_plan = None
            if str(analyzer_key) in {"step", "parasolid"}:
                adapter = self.process_registry.get(process)
                defaults = adapter.compile(context, {})
                raw_parameters = {
                    fact.name: {
                        "value": fact.value,
                        "source": "project_fact",
                        "source_ref": f"fact:{fact.fact_id}",
                    }
                    for fact in manifest.facts
                    if fact.status == "confirmed"
                    and fact.name in defaults.accepted_inputs
                }
                process_plan = adapter.compile(context, raw_parameters)
            parent_plan_id = str(params.get("base_plan_id") or "") or None
            parent_plan = next(
                (item for item in manifest.plans if item.plan_id == parent_plan_id), None
            )
            if parent_plan_id and parent_plan is None:
                raise DFMError("plan_not_found", "Base DFM analysis plan was not found.", {"plan_id": parent_plan_id})
            if parent_plan is not None and parent_plan.status != "invalidated":
                raise DFMError("plan_not_rebuildable", "Only an invalidated plan can be rebuilt incrementally.", {"plan_id": parent_plan_id, "status": parent_plan.status})
            operations = self._operation_closure(
                process_plan.operations if process_plan else [],
                parent_plan.affected_operation_ids if parent_plan else [],
            )
            operation_ids = {item.operation_id for item in operations}
            rule_bindings = (
                [
                    item
                    for item in process_plan.rule_bindings
                    if item.operation_id in operation_ids
                ]
                if process_plan
                else []
            )
            active_inputs = self._active_inputs(manifest)
            now = _utc_now()
            plan = PlanRecord(
                f"plan_{uuid4().hex[:16]}",
                manifest.input_mode or str(analyzer_key),
                [str(analyzer_key)],
                "ready" if capability.status.value == "available" else "blocked",
                now,
                process=process_plan.process if process_plan else "",
                process_adapter_version=process_plan.adapter_version if process_plan else "",
                scope_id=process_plan.scope_id if process_plan else "",
                scope_version=process_plan.scope_version if process_plan else "",
                input_ids=[item.input_id for item in active_inputs],
                input_hashes={item.input_id: item.sha256 for item in active_inputs},
                rules=process_plan.rules if process_plan else {},
                rule_bindings=rule_bindings,
                operations=operations,
                parent_plan_id=parent_plan_id,
            )
            capability = analyzer.capability(self._context(manifest, plan))
            plan = replace(
                plan,
                status="ready" if capability.status.value == "available" else "blocked",
            )
            store.update(lambda current: replace(current, plans=[*current.plans, plan], updated_at=_utc_now()))
            return {"ok": True, "project_id": project_id, "plan": plan.to_dict(), "capability": capability.to_dict()}
        if action == "start":
            manifest = self._store(project_id).load()
            plan_id = params.get("plan_id")
            plan = next((item for item in manifest.plans if item.plan_id == plan_id), None)
            if plan is None:
                raise DFMError("plan_not_found", "DFM analysis plan was not found.", {"plan_id": plan_id})
            # A capability-blocked plan is still useful for surfacing the
            # analyzer's explicit dependency error. Only changed project state
            # makes a saved plan stale and unsafe to execute.
            if plan.status == "invalidated":
                raise DFMError(
                    "plan_not_ready",
                    "DFM analysis plan is no longer executable; create a new plan.",
                    {"plan_id": plan.plan_id, "status": plan.status},
                )
            progress_callback = params.get("_tool_progress_callback")
            tool_call_id = str(params.get("_tool_call_id") or "")

            def on_update(updated: RunRecord) -> None:
                if not callable(progress_callback):
                    return
                terminal = updated.status in {
                    RunStatus.SUCCEEDED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                    RunStatus.BLOCKED,
                }
                latest = updated.artifacts[-1] if updated.artifacts else None
                latest_text = (
                    f", latest {latest.kind}: {latest.relative_path}"
                    if latest is not None
                    else ""
                )
                preview = (
                    f"DFM {updated.status.value}: {updated.stage or 'working'} "
                    f"({updated.progress_percent}%, {len(updated.artifacts)} artifacts{latest_text})"
                )
                try:
                    progress_callback(
                        "background.tool.complete" if terminal else "background.tool.progress",
                        "dfm_analysis",
                        preview,
                        None,
                        tool_id=tool_call_id,
                        status=updated.status.value,
                        stage=updated.stage,
                        percent=updated.progress_percent,
                        artifact_count=len(updated.artifacts),
                        latest_artifact=(latest.relative_path if latest else None),
                        latest_artifact_kind=(latest.kind if latest else None),
                        run_id=updated.run_id,
                        is_error=updated.status in {RunStatus.FAILED, RunStatus.BLOCKED},
                    )
                except Exception:
                    return

            run = self.jobs.start(
                project_id,
                plan.analyzer_keys[0],
                plan=plan,
                idempotency_key=params.get("idempotency_key"),
                on_update=on_update,
            )
            return {"ok": True, "project_id": project_id, "run": self._run_dict(project_id, run)}
        run_id = self._resolve_run_id(
            self._store(project_id).load(), params.get("run_id"), action
        )
        if action == "status":
            run = self.jobs.status(project_id, run_id)
        elif action == "cancel":
            run = self.jobs.cancel(project_id, run_id)
        elif action == "result":
            run = self.jobs.result(project_id, run_id)
        else:
            raise DFMError("action_invalid", f"Unsupported dfm_analysis action: {action}")
        return {"ok": True, "project_id": project_id, "run": self._run_dict(project_id, run)}

    def _run_dict(self, project_id: str, run: RunRecord) -> dict[str, Any]:
        payload = run.to_dict()
        project_dir = self.workspace.project_dir(project_id)
        payload["artifacts"] = [{**artifact.to_dict(), "path": str((project_dir / artifact.relative_path).resolve())} for artifact in run.artifacts]
        payload["diagnostics"] = {
            key: str((project_dir / relative).resolve())
            for key, relative in {
                "events": run.event_log_path,
                "stdout": run.worker_stdout_path,
                "stderr": run.worker_stderr_path,
            }.items()
            if relative
        }
        return payload

    def close(self) -> None:
        self.jobs.shutdown()


_SERVICES: dict[Path, DFMService] = {}
_SERVICES_LOCK = threading.Lock()


def get_dfm_service() -> DFMService:
    home = get_hermes_home().resolve()
    with _SERVICES_LOCK:
        service = _SERVICES.get(home)
        if service is None:
            service = DFMService()
            _SERVICES[home] = service
        return service
