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
    assert tuple(adapter.required_facts()) == ("model_units",)


def test_injection_default_scope_has_versioned_parameter_provenance(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {})

    assert plan.process == "injection"
    assert plan.scope_id == "injection.geometry-core"
    assert plan.scope_version == "4.0.0"
    assert plan.adapter_version == "injection-geometry-core-v4"
    assert plan.rules["min_wall_mm"].source == (
        "scope:injection.geometry-core@4.0.0/parameters/min_wall_mm"
    )
    assert plan.rules["min_draft_deg"].value == 1.0
    assert plan.rules["min_draft_deg"].source == (
        "scope:injection.geometry-core@4.0.0/parameters/min_draft_deg"
    )
    assert plan.rules["min_draft_deg"].unit == "degree"
    assert plan.operations[0].calculator_id == "geometry_preflight"
    assert plan.operations[0].arguments["model_unit"].value == "mm"
    assert [item.calculator_id for item in plan.operations] == [
        "geometry_preflight",
        "index_topology",
        "build_aag",
        "measure_draft",
        "measure_wall_thickness",
        "measure_undercut",
        "measure_sharp_corner",
        "recognize_drilled_hole",
        "recognize_blend",
        "recognize_shaft",
        "recognize_cavity",
        "recognize_convex_hull",
        "recognize_isolated",
        "recognize_canonical_surface",
        "recognize_surface_probe",
        "recognize_chamfer",
        "recognize_rib",
    ]
    assert {item.quantity_id for item in plan.rule_bindings} == {
        "thickness_mm",
        "draft_angle_deg",
        "undercut_count",
        "corner_angle_deg",
    }
    assert all(
        "topology_map" in item.required_artifacts
        for item in plan.operations
        if item.calculator_id.startswith("measure_")
    )
    wall = next(
        item
        for item in plan.operations
        if item.calculator_id == "measure_wall_thickness"
    )
    assert wall.required_quantities == ["thickness_mm", "average_thickness_mm"]
    assert tuple(adapter.required_facts()) == ("model_units",)


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
    draft = next(
        item for item in plan.operations if item.calculator_id == "measure_draft"
    )
    undercut = next(
        item for item in plan.operations if item.calculator_id == "measure_undercut"
    )
    assert draft.arguments["pull_direction"].value == [0.0, 1.0, 0.0]
    assert draft.arguments["pull_direction"].source_ref == "fact:fact_pull_direction"
    assert undercut.arguments["pull_direction"].value == [0.0, 1.0, 0.0]


def test_injection_geometry_plan_does_not_require_or_forward_material(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {"model_units": "mm"})

    assert plan.rules["min_wall_mm"].value == 1.2
    assert all("material" not in item.arguments for item in plan.operations)


@pytest.mark.parametrize(
    ("model_units", "expected"),
    [("inch", "inch"), ("IN", "inch"), ("centimetres", "cm"), ("ft", "foot")],
)
def test_step_source_units_are_normalized_and_preserved_in_preflight_plan(
    context, model_units, expected
):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {"model_units": model_units})

    preflight = next(
        item for item in plan.operations if item.calculator_id == "geometry_preflight"
    )
    assert preflight.arguments["model_unit"].value == expected


@pytest.mark.parametrize("model_units", ["parsec", "unknown"])
def test_scope_rejects_unknown_model_units(context, model_units):
    adapter = build_default_process_registry().get("injection")

    with pytest.raises(DFMError) as exc_info:
        adapter.compile(context, {"model_units": model_units})

    assert exc_info.value.code == "process_parameter_invalid"


@pytest.mark.parametrize(
    "parameters",
    [
        {"material": "ABS"},
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
