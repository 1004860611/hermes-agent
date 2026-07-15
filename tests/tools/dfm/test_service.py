from pathlib import Path

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools.dfm.analyzers.drawing import DrawingAnalyzer
from tools.dfm.analyzers.fusion import FusionAnalyzer
from tools.dfm.analyzers.registry import AnalyzerRegistry
from tools.dfm.analyzers.step import StepAnalyzer
from tools.dfm.errors import DFMError
from tools.dfm.service import DFMService


@pytest.fixture
def service(tmp_path):
    token = set_hermes_home_override(tmp_path / "home")
    registry = AnalyzerRegistry()
    registry.register(StepAnalyzer(dependency_probe=lambda: False))
    registry.register(DrawingAnalyzer())
    registry.register(FusionAnalyzer())
    instance = DFMService(registry=registry, reconcile_jobs=False)
    try:
        yield instance, tmp_path
    finally:
        instance.close()
        reset_hermes_home_override(token)


def test_project_actions_create_add_input_status_confirm_and_list(service):
    dfm, temp = service
    created = dfm.project("create", name="Bracket", idempotency_key="create-1")
    source = temp / "part.step"
    source.write_bytes(b"opaque-step")

    added = dfm.project("add_input", project_id=created["project_id"], path=str(source))
    confirmed = dfm.project(
        "confirm_fact",
        project_id=created["project_id"],
        fact_name="material",
        fact_value="ABS",
    )
    status = dfm.project("status", project_id=created["project_id"])
    listed = dfm.project("list")

    assert added["input"]["kind"] == "step"
    assert confirmed["fact"]["status"] == "confirmed"
    assert status["project"]["input_mode"] == "step"
    assert status["capabilities"]["step"]["status"] == "dependency_missing"
    assert listed["projects"][0]["project_id"] == created["project_id"]


def test_plan_is_persisted_but_unavailable_production_start_fails_explicitly(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(b"opaque-step")
    added = dfm.project("add_input", project_id=project_id, path=str(source))

    plan = dfm.analysis("plan", project_id=project_id)

    assert plan["plan"]["analyzer_keys"] == ["step"]
    assert plan["plan"]["process"] == "injection"
    assert plan["plan"]["scope_id"] == "injection.legacy-baseline"
    assert plan["plan"]["scope_version"] == "1.0.0"
    assert plan["plan"]["input_ids"] == [plan["plan"]["input_ids"][0]]
    assert set(plan["plan"]["input_hashes"].values()) == {
        added["input"]["sha256"]
    }
    assert plan["plan"]["parameters"]["min_draft_deg"] == {
        "value": 1.0,
        "unit": "degree",
        "source": "injection_legacy_default",
    }
    assert plan["capability"]["status"] == "dependency_missing"
    with pytest.raises(DFMError) as exc_info:
        dfm.analysis("start", project_id=project_id, plan_id=plan["plan"]["plan_id"])
    assert exc_info.value.code == "dependency_missing"


def test_desktop_file_reference_prefix_is_accepted(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = Path(temp / "part.step")
    source.write_bytes(b"opaque-step")

    result = dfm.project("add_input", project_id=project_id, path=f"@file:{source}")

    assert result["input"]["source_name"] == "part.step"
