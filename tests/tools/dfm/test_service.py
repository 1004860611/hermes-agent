from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools.dfm.analyzers.drawing import DrawingAnalyzer
from tools.dfm.analyzers.fusion import FusionAnalyzer
from tools.dfm.analyzers.parasolid import ParasolidAnalyzer
from tools.dfm.analyzers.registry import AnalyzerRegistry
from tools.dfm.analyzers.step import StepAnalyzer
from tools.dfm.errors import DFMError
from tools.dfm.service import DFMService


STEP_PAYLOAD = (
    Path(__file__).parents[3] / "tests" / "fixtures" / "dfm" / "step" / "injection_plate_with_hole.step"
).read_bytes()


def confirm_step_facts(dfm, project_id):
    for name, value in {
        "material": "ABS",
        "pull_dir": [0, 0, 1],
        "model_units": "mm",
    }.items():
        dfm.project(
            "confirm_fact", project_id=project_id, fact_name=name, fact_value=value
        )


@pytest.fixture
def service(tmp_path):
    token = set_hermes_home_override(tmp_path / "home")
    registry = AnalyzerRegistry()
    registry.register(StepAnalyzer(dependency_probe=lambda: False))
    registry.register(DrawingAnalyzer())
    registry.register(FusionAnalyzer())
    registry.register(ParasolidAnalyzer())
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
    source.write_bytes(STEP_PAYLOAD)

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
    assert {item["clarification_id"] for item in added["open_clarifications"]} == {
        "clarification_material",
        "clarification_pull_dir",
        "clarification_model_units",
    }
    assert confirmed["fact"]["status"] == "confirmed"
    assert status["project"]["input_mode"] == "step"
    assert next(
        item
        for item in status["project"]["clarifications"]
        if item["clarification_id"] == "clarification_material"
    ) == {
        "clarification_id": "clarification_material",
        "question": "What resin/material grade will be used for this part?",
        "status": "answered",
        "answer": "ABS",
    }
    assert {item["clarification_id"] for item in status["project"]["open_clarifications"]} == {
        "clarification_pull_dir",
        "clarification_model_units",
    }
    assert status["capabilities"]["step"]["status"] == "dependency_missing"
    assert listed["projects"][0]["project_id"] == created["project_id"]


def test_fact_alias_units_closes_model_units_clarification(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(STEP_PAYLOAD)
    dfm.project("add_input", project_id=project_id, path=str(source))

    confirmed = dfm.project(
        "confirm_fact", project_id=project_id, fact_name="units", fact_value="mm"
    )
    status = dfm.project("status", project_id=project_id)

    assert confirmed["fact"]["name"] == "model_units"
    assert confirmed["fact"]["value"] == "mm"
    assert "clarification_model_units" not in {
        item["clarification_id"] for item in status["project"]["open_clarifications"]
    }
    row = next(
        item
        for item in status["project"]["clarifications"]
        if item["clarification_id"] == "clarification_model_units"
    )
    assert row["status"] == "answered"


def test_missing_run_id_is_recovered_only_when_unambiguous():
    one = SimpleNamespace(run_id="run_only", status="running")
    manifest = SimpleNamespace(runs=[one])
    assert DFMService._resolve_run_id(manifest, None, "status") == "run_only"

    many = SimpleNamespace(
        runs=[
            SimpleNamespace(run_id="run_a", status="succeeded"),
            SimpleNamespace(run_id="run_b", status="running"),
        ]
    )
    assert DFMService._resolve_run_id(many, None, "status") == "run_b"

    ambiguous = SimpleNamespace(
        runs=[
            SimpleNamespace(run_id="run_a", status="running"),
            SimpleNamespace(run_id="run_b", status="running"),
        ]
    )
    with pytest.raises(DFMError) as exc_info:
        DFMService._resolve_run_id(ambiguous, None, "status")
    assert exc_info.value.code == "run_id_required"


def test_plan_is_persisted_but_unavailable_production_start_fails_explicitly(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(STEP_PAYLOAD)
    added = dfm.project("add_input", project_id=project_id, path=str(source))

    blocked = dfm.analysis("plan", project_id=project_id)
    assert blocked["status"] == "clarification_required"
    assert blocked["requires_user_response"] is True
    assert blocked["next_action"] == "clarify"
    assert blocked["do_not_infer"] is True
    assert len(blocked["clarifications"]) == 3
    confirm_step_facts(dfm, project_id)
    plan = dfm.analysis("plan", project_id=project_id)

    assert plan["plan"]["analyzer_keys"] == ["step"]
    assert plan["plan"]["process"] == "injection"
    assert plan["plan"]["scope_id"] == "injection.legacy-baseline"
    assert plan["plan"]["scope_version"] == "1.1.0"
    assert plan["plan"]["input_ids"] == [plan["plan"]["input_ids"][0]]
    assert set(plan["plan"]["input_hashes"].values()) == {added["input"]["sha256"]}
    assert plan["plan"]["rules"]["min_draft_deg"] == {
        "value": 1.0,
        "unit": "degree",
        "source": "scope:injection.legacy-baseline@1.1.0/parameters/min_draft_deg",
        "version": "1.1.0",
    }
    assert plan["capability"]["status"] == "dependency_missing"
    with pytest.raises(DFMError) as exc_info:
        dfm.analysis("start", project_id=project_id, plan_id=plan["plan"]["plan_id"])
    assert exc_info.value.code == "dependency_missing"


def test_input_or_confirmed_fact_invalidates_prior_plan(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(STEP_PAYLOAD)
    dfm.project("add_input", project_id=project_id, path=str(source))
    confirm_step_facts(dfm, project_id)
    plan = dfm.analysis("plan", project_id=project_id)["plan"]

    dfm.project(
        "confirm_fact",
        project_id=project_id,
        fact_name="material",
        fact_value="PC",
    )

    with pytest.raises(DFMError) as exc_info:
        dfm.analysis("start", project_id=project_id, plan_id=plan["plan_id"])
    assert exc_info.value.code == "plan_not_ready"
    assert exc_info.value.details["status"] == "invalidated"


def test_new_input_version_supersedes_prior_input_and_replans_full_scope(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(STEP_PAYLOAD)
    first = dfm.project("add_input", project_id=project_id, path=str(source))["input"]
    confirm_step_facts(dfm, project_id)
    plan = dfm.analysis("plan", project_id=project_id)["plan"]

    source.write_bytes(STEP_PAYLOAD + b"\n/* revised */\n")
    second = dfm.project("add_input", project_id=project_id, path=str(source))["input"]
    rebuilt = dfm.analysis(
        "plan", project_id=project_id, base_plan_id=plan["plan_id"]
    )["plan"]

    assert second["supersedes_input_id"] == first["input_id"]
    assert rebuilt["parent_plan_id"] == plan["plan_id"]
    assert rebuilt["input_ids"] == [second["input_id"]]
    assert rebuilt["operations"] == plan["operations"]


def test_pull_direction_rebuild_only_includes_affected_operation_closure(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = temp / "part.step"
    source.write_bytes(STEP_PAYLOAD)
    dfm.project("add_input", project_id=project_id, path=str(source))
    confirm_step_facts(dfm, project_id)
    plan = dfm.analysis("plan", project_id=project_id)["plan"]

    dfm.project(
        "confirm_fact", project_id=project_id, fact_name="pull_dir", fact_value=[1, 0, 0]
    )
    rebuilt = dfm.analysis(
        "plan", project_id=project_id, base_plan_id=plan["plan_id"]
    )["plan"]

    assert [item["operation_id"] for item in rebuilt["operations"]] == [
        "geometry.load",
        "geometry.topology",
        "geometry.draft",
        "geometry.undercut",
    ]


def test_desktop_file_reference_prefix_is_accepted(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Bracket")["project_id"]
    source = Path(temp / "part.step")
    source.write_bytes(STEP_PAYLOAD)

    result = dfm.project("add_input", project_id=project_id, path=f"@file:{source}")

    assert result["input"]["source_name"] == "part.step"


def test_die_casting_plan_uses_its_own_facts_scope_and_operations(service):
    dfm, temp = service
    project_id = dfm.project("create", name="Die-cast housing")["project_id"]
    source = temp / "housing.step"
    source.write_bytes(STEP_PAYLOAD)
    dfm.project("add_input", project_id=project_id, path=str(source))

    blocked = dfm.analysis("plan", project_id=project_id, process="die_casting")

    assert [item["clarification_id"] for item in blocked["clarifications"]] == [
        "clarification_model_units"
    ]
    dfm.project(
        "confirm_fact",
        project_id=project_id,
        fact_name="model_units",
        fact_value="mm",
    )
    result = dfm.analysis("plan", project_id=project_id, process="die_casting")
    status = dfm.project("status", project_id=project_id)

    assert result["plan"]["process"] == "die_casting"
    assert result["plan"]["scope_id"] == "die_casting.topology-baseline"
    assert [item["calculator_id"] for item in result["plan"]["operations"]] == [
        "load_geometry",
        "inspect_topology",
    ]
    assert status["project"]["process"] == "die_casting"
    assert status["project"]["process_source"] == "user_selected"


def test_parasolid_capability_is_local_and_does_not_disable_step(service):
    dfm, temp = service
    project_id = dfm.project("create", name="NX backend capability")["project_id"]
    source = temp / "part.x_t"
    source.write_text("Parasolid transmit text file\nbody data\n", encoding="ascii")
    dfm.project("add_input", project_id=project_id, path=str(source))

    status = dfm.project("status", project_id=project_id)

    assert status["project"]["inputs"][0]["format_id"] == "parasolid_xt"
    assert status["capabilities"]["parasolid"]["status"] == "dependency_missing"
    assert status["capabilities"]["step"]["status"] == "dependency_missing"
    plan = dfm.analysis("plan", project_id=project_id)
    assert plan["plan"]["status"] == "blocked"
    assert plan["capability"]["status"] == "dependency_missing"
