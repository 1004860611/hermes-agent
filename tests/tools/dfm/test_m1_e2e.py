import json
from pathlib import Path
import time

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tests.tools.dfm.baseline import occ_available


FIXTURE = Path("tests/fixtures/dfm/step/injection_plate_with_hole.step").resolve()


def _dispatch(registry, name, arguments):
    return json.loads(registry.dispatch(name, arguments))


@pytest.mark.skipif(not occ_available(), reason="real M1 E2E requires pythonocc-core")
def test_m1_real_tool_vertical_slice(tmp_path):
    from model_tools import get_tool_definitions
    from tools.dfm.service import get_dfm_service
    from tools.registry import discover_builtin_tools, registry

    token = set_hermes_home_override(tmp_path / "home")
    discover_builtin_tools()
    try:
        enabled = {
            item["function"]["name"]
            for item in get_tool_definitions(enabled_toolsets=["hermes-cli", "dfm"])
        }
        assert {"dfm_project", "dfm_analysis"} <= enabled

        project = _dispatch(registry, "dfm_project", {"action": "create", "name": "M1 E2E"})
        project_id = project["project_id"]
        _dispatch(
            registry,
            "dfm_project",
            {"action": "add_input", "project_id": project_id, "path": str(FIXTURE)},
        )
        plan = _dispatch(registry, "dfm_analysis", {"action": "plan", "project_id": project_id})
        assert plan["plan"]["process"] == "injection"
        assert plan["plan"]["scope_id"] == "injection.legacy-baseline"
        assert plan["capability"]["status"] == "available"

        started = _dispatch(
            registry,
            "dfm_analysis",
            {
                "action": "start",
                "project_id": project_id,
                "plan_id": plan["plan"]["plan_id"],
            },
        )
        run_id = started["run"]["run_id"]
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            status = _dispatch(
                registry,
                "dfm_analysis",
                {"action": "status", "project_id": project_id, "run_id": run_id},
            )
            if status["run"]["status"] in {"succeeded", "failed", "blocked", "cancelled"}:
                break
            time.sleep(0.1)
        else:
            pytest.fail("M1 real tool run did not reach a terminal state")

        result = _dispatch(
            registry,
            "dfm_analysis",
            {"action": "result", "project_id": project_id, "run_id": run_id},
        )
        assert result["run"]["status"] == "succeeded", result["run"]
        assert result["run"]["plan_snapshot"] == plan["plan"]
        assert {item["kind"] for item in result["run"]["artifacts"]} >= {
            "report_json",
            "report_markdown",
            "report_presentation",
            "worker_result",
        }
        assert all(Path(item["path"]).is_file() for item in result["run"]["artifacts"])
    finally:
        get_dfm_service().close()
        reset_hermes_home_override(token)
