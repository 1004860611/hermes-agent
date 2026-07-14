"""M0 vertical-slice acceptance tests for the built-in DFM capability."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from model_tools import get_tool_definitions
from tools.dfm.analyzers.base import AnalyzerContext
from tools.dfm.analyzers.registry import AnalyzerRegistry
from tools.dfm.config import DFMConfig
from tools.dfm.contracts import (
    ArtifactRecord,
    Capability,
    CapabilityStatus,
    RunStatus,
)
from tools.dfm.project.workspace import DFMWorkspace
from tools.dfm.service import DFMService, get_dfm_service
from tools.registry import discover_builtin_tools, registry


def _tool_names(toolsets: list[str]) -> set[str]:
    return {
        definition["function"]["name"]
        for definition in get_tool_definitions(enabled_toolsets=toolsets)
    }


def _dispatch(name: str, arguments: dict) -> dict:
    return json.loads(registry.dispatch(name, arguments))


def test_production_step_vertical_slice_fails_explicitly_without_fake_results(tmp_path):
    discover_builtin_tools()
    core_names = _tool_names(["hermes-cli"])
    enabled_definitions = get_tool_definitions(
        enabled_toolsets=["hermes-cli", "dfm"]
    )
    enabled_names = {
        definition["function"]["name"] for definition in enabled_definitions
    }

    assert {"dfm_project", "dfm_analysis"}.isdisjoint(core_names)
    assert {"dfm_project", "dfm_analysis"} <= enabled_names

    token = set_hermes_home_override(tmp_path / "home")
    source = tmp_path / "opaque.step"
    source.write_bytes(b"synthetic opaque STEP payload")
    try:
        created = _dispatch(
            "dfm_project",
            {"action": "create", "name": "M0 production acceptance"},
        )
        project_id = created["project_id"]
        _dispatch(
            "dfm_project",
            {
                "action": "add_input",
                "project_id": project_id,
                "path": f"@file:{source}",
            },
        )
        status = _dispatch(
            "dfm_project",
            {"action": "status", "project_id": project_id},
        )
        plan = _dispatch(
            "dfm_analysis",
            {"action": "plan", "project_id": project_id},
        )
        started = _dispatch(
            "dfm_analysis",
            {
                "action": "start",
                "project_id": project_id,
                "plan_id": plan["plan"]["plan_id"],
            },
        )
        final_status = _dispatch(
            "dfm_project",
            {"action": "status", "project_id": project_id},
        )
        schemas_after = get_tool_definitions(
            enabled_toolsets=["hermes-cli", "dfm"]
        )
    finally:
        get_dfm_service().close()
        reset_hermes_home_override(token)

    assert status["project"]["input_mode"] == "step"
    assert status["capabilities"]["step"]["status"] == "dependency_missing"
    assert plan["plan"]["status"] == "blocked"
    assert started["ok"] is False
    assert started["error"]["code"] == "dependency_missing"
    assert final_status["project"]["runs"] == []
    assert final_status["project"]["findings"] == []
    assert final_status["project"]["artifacts"] == []
    assert schemas_after == enabled_definitions


class SuccessfulTestAnalyzer:
    key = "step"
    version = "m0-test-only"
    supported_inputs = ("step",)

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(self.key, CapabilityStatus.AVAILABLE, "test only")

    def run(self, context: AnalyzerContext, cancellation) -> list[ArtifactRecord]:
        cancellation.raise_if_cancelled()
        relative_path = f"artifacts/{context.run_id}.json"
        output = context.project_dir / relative_path
        output.write_text('{"accepted": true}', encoding="utf-8")
        return [
            ArtifactRecord(
                artifact_id=f"artifact_{context.run_id}",
                kind="diagnostic",
                relative_path=relative_path,
                media_type="application/json",
                created_at="2026-07-14T00:00:00Z",
            )
        ]


def test_injected_analyzer_vertical_slice_returns_desktop_compatible_artifact(tmp_path):
    token = set_hermes_home_override(tmp_path / "home")
    analyzer_registry = AnalyzerRegistry()
    analyzer_registry.register(SuccessfulTestAnalyzer())
    service = DFMService(
        config=DFMConfig(max_concurrent_runs=1),
        workspace=DFMWorkspace(),
        registry=analyzer_registry,
        reconcile_jobs=False,
    )
    source = tmp_path / "accepted.step"
    source.write_bytes(b"synthetic test analyzer input")
    try:
        project_id = service.project("create", name="M0 success acceptance")[
            "project_id"
        ]
        service.project(
            "add_input",
            project_id=project_id,
            path=f"@file:{source}",
        )
        plan = service.analysis("plan", project_id=project_id)
        started = service.analysis(
            "start",
            project_id=project_id,
            plan_id=plan["plan"]["plan_id"],
        )
        run_id = started["run"]["run_id"]

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            observed = service.analysis(
                "status",
                project_id=project_id,
                run_id=run_id,
            )
            if observed["run"]["status"] == RunStatus.SUCCEEDED.value:
                break
            time.sleep(0.01)
        else:
            pytest.fail(f"run did not succeed: {observed}")

        result = service.analysis(
            "result",
            project_id=project_id,
            run_id=run_id,
        )
    finally:
        service.close()
        reset_hermes_home_override(token)

    artifact = result["run"]["artifacts"][0]
    assert artifact["relative_path"] == f"artifacts/{run_id}.json"
    artifact_path = Path(artifact["path"])
    assert artifact_path.is_absolute()
    assert artifact_path.is_file()
    assert artifact_path == (
        service.workspace.project_dir(project_id) / artifact["relative_path"]
    ).resolve()
