"""Application service behind the stable Hermes DFM tool schemas."""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from hermes_constants import get_hermes_home

from .analyzers.base import AnalyzerContext
from .analyzers.registry import AnalyzerRegistry, build_default_registry
from .config import DFMConfig, load_dfm_config
from .contracts import FactRecord, PlanRecord, ProjectManifest, RunRecord
from .errors import DFMError
from .project.inputs import InputRegistrar
from .project.manifest import ManifestStore
from .project.workspace import DFMWorkspace
from .runtime.jobs import JobManager


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class DFMService:
    def __init__(self, *, config: DFMConfig | None = None, workspace: DFMWorkspace | None = None, registry: AnalyzerRegistry | None = None, reconcile_jobs: bool = True) -> None:
        self.config = config or load_dfm_config()
        self.workspace = workspace or DFMWorkspace()
        self.registry = registry or build_default_registry()
        self.inputs = InputRegistrar(self.workspace, self.config)
        self.jobs = JobManager(self.workspace, self.registry, self.config, reconcile=reconcile_jobs)

    def _store(self, project_id: str) -> ManifestStore:
        return ManifestStore(self.workspace.project_dir(project_id))

    def _context(self, manifest: ProjectManifest) -> AnalyzerContext:
        return AnalyzerContext(manifest.project_id, self.workspace.project_dir(manifest.project_id), manifest.input_mode, manifest.inputs)

    def _capabilities(self, manifest: ProjectManifest) -> dict[str, dict[str, Any]]:
        context = self._context(manifest)
        return {key: self.registry.get(key).capability(context).to_dict() for key in self.registry.keys()}

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
            raw_path = str(params.get("path") or "")
            if raw_path.startswith("@file:"):
                raw_path = raw_path[len("@file:"):]
            record = self.inputs.register(project_id, raw_path.strip().strip('"'))
            return {"ok": True, "project_id": project_id, "input": record.to_dict()}
        if action == "confirm_fact":
            name = str(params.get("fact_name") or "").strip()
            if not name:
                raise DFMError("fact_invalid", "fact_name is required.")
            fact = FactRecord(f"fact_{uuid4().hex[:16]}", name, params.get("fact_value"), "user", "confirmed")
            manifest = self._store(project_id).update(lambda current: replace(current, facts=[*current.facts, fact], updated_at=_utc_now()))
            return {"ok": True, "project_id": project_id, "fact": fact.to_dict(), "revision": manifest.revision}
        if action == "status":
            manifest = self._store(project_id).load()
            return {"ok": True, "project": manifest.to_dict(), "capabilities": self._capabilities(manifest)}
        raise DFMError("action_invalid", f"Unsupported dfm_project action: {action}")

    def analysis(self, action: str, **params: Any) -> dict[str, Any]:
        project_id = params.get("project_id") or ""
        if action == "plan":
            store = self._store(project_id)
            manifest = store.load()
            analyzer_key = params.get("analyzer_key") or manifest.input_mode
            if not analyzer_key:
                raise DFMError("input_required", "Register a DFM input before planning analysis.")
            analyzer = self.registry.get(str(analyzer_key))
            capability = analyzer.capability(self._context(manifest))
            plan = PlanRecord(f"plan_{uuid4().hex[:16]}", manifest.input_mode or str(analyzer_key), [str(analyzer_key)], "ready" if capability.status.value == "available" else "blocked", _utc_now())
            store.update(lambda current: replace(current, plans=[*current.plans, plan], updated_at=_utc_now()))
            return {"ok": True, "project_id": project_id, "plan": plan.to_dict(), "capability": capability.to_dict()}
        if action == "start":
            manifest = self._store(project_id).load()
            plan_id = params.get("plan_id")
            plan = next((item for item in manifest.plans if item.plan_id == plan_id), None)
            if plan is None:
                raise DFMError("plan_not_found", "DFM analysis plan was not found.", {"plan_id": plan_id})
            run = self.jobs.start(project_id, plan.analyzer_keys[0], idempotency_key=params.get("idempotency_key"))
            return {"ok": True, "project_id": project_id, "run": self._run_dict(project_id, run)}
        run_id = params.get("run_id") or ""
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
