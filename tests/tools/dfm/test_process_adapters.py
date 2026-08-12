from pathlib import Path

import pytest

from tools.dfm.analyzers.base import AnalyzerContext
from tools.dfm.errors import DFMError
from tools.dfm.processes.registry import build_default_process_registry


@pytest.fixture
def context(tmp_path):
    return AnalyzerContext(
        project_id="dfm_project",
        project_dir=Path(tmp_path),
        input_mode="step",
        inputs=[],
    )


def test_default_process_registry_supports_injection_and_die_casting():
    registry = build_default_process_registry()

    assert registry.keys() == ("die_casting", "injection")
    with pytest.raises(DFMError) as exc_info:
        registry.get("machining")

    assert exc_info.value.code == "unsupported_capability"
    assert exc_info.value.details["supported_processes"] == ["die_casting", "injection"]


def test_die_casting_scope_is_independent_and_topology_only(context):
    adapter = build_default_process_registry().get("die_casting")

    plan = adapter.compile(context, {})

    assert plan.process == "die_casting"
    assert plan.scope_id == "die_casting.topology-baseline"
    assert plan.scope_version == "1.0.0"
    assert [item.calculator_id for item in plan.operations] == [
        "load_geometry",
        "inspect_topology",
    ]
    assert tuple(adapter.required_facts()) == ("process", "model_units")


def test_injection_default_scope_has_versioned_parameter_provenance(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {})

    assert plan.process == "injection"
    assert plan.scope_id == "injection.wall-draft"
    assert plan.scope_version == "3.0.0"
    assert plan.adapter_version == "injection-wall-draft-v3"
    assert plan.rules["min_wall_mm"].source == (
        "scope:injection.wall-draft@3.0.0/materials/ABS/min_wall_mm"
    )
    assert plan.rules["min_draft_deg"].value == 1.0
    assert plan.rules["min_draft_deg"].source == (
        "scope:injection.wall-draft@3.0.0/parameters/min_draft_deg"
    )
    assert plan.rules["min_draft_deg"].unit == "degree"
    assert plan.operations[0].calculator_id == "load_geometry"
    assert plan.operations[0].arguments["model_unit"].value == "mm"
    assert [item.calculator_id for item in plan.operations] == [
        "load_geometry",
        "inspect_topology",
        "measure_wall_thickness",
        "measure_draft",
    ]
    assert {item.quantity_id for item in plan.rule_bindings} == {
        "thickness_mm",
        "draft_angle_deg",
    }
    wall_operation = next(
        item for item in plan.operations if item.calculator_id == "measure_wall_thickness"
    )
    wall_binding = next(
        item for item in plan.rule_bindings if item.quantity_id == "thickness_mm"
    )
    assert wall_operation.required_fact_names == ["model_units"]
    assert wall_binding.required_fact_names == ["material"]
    requirements = {item.name: item for item in adapter.fact_requirements()}
    assert requirements["process"].phase == "discovery"
    assert requirements["model_units"].phase == "discovery"
    assert requirements["material"].required_by == ("rule.wall_thickness",)
    assert requirements["pull_dir"].required_by == ("geometry.draft",)
    measured = plan.operations[2:]
    assert all(
        item.required_artifacts == [
            "scalar_field",
            "render_scene",
            "topology_map",
        ]
        for item in measured
    )


def test_confirmed_parameter_override_is_normalized_and_traced(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(
        context,
        {
            "min_wall_mm": {"value": "1.6", "source": "project_fact"},
            "pull_dir": {
                "value": [0, 1, 0],
                "source": "user_confirmed",
                "source_ref": "fact:fact_pull_direction",
            },
        },
    )

    assert plan.rules["min_wall_mm"].value == 1.6
    assert plan.rules["min_wall_mm"].source == "fact:min_wall_mm"
    draft = next(item for item in plan.operations if item.calculator_id == "measure_draft")
    assert draft.arguments["pull_direction"].value == [0.0, 1.0, 0.0]
    assert draft.arguments["pull_direction"].source_ref == "fact:fact_pull_direction"


def test_material_profile_changes_hermes_rule_without_entering_backend_arguments(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {"material": "ABS", "model_units": "mm"})

    assert plan.rules["min_wall_mm"].value == 1.2
    assert all("material" not in item.arguments for item in plan.operations)


@pytest.mark.parametrize("model_units", ["inch", "cm", "unknown"])
def test_frozen_scope_rejects_unsupported_model_units(context, model_units):
    adapter = build_default_process_registry().get("injection")

    with pytest.raises(DFMError) as exc_info:
        adapter.compile(context, {"model_units": model_units})

    assert exc_info.value.code == "process_parameter_invalid"


@pytest.mark.parametrize(
    "parameters",
    [
        {"imaginary_threshold": 1},
        {"min_wall_mm": 0},
        {"pull_dir": [0, 0]},
        {"min_draft_deg": {"value": 1, "source": "model_guess"}},
    ],
)
def test_injection_adapter_rejects_unknown_or_untrusted_parameters(context, parameters):
    adapter = build_default_process_registry().get("injection")

    with pytest.raises(DFMError) as exc_info:
        adapter.compile(context, parameters)

    assert exc_info.value.code == "process_parameter_invalid"
