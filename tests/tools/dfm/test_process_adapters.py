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
    assert [item.operation for item in plan.operations] == [
        "load_step",
        "inspect_topology",
    ]
    assert tuple(adapter.required_facts()) == ("model_units",)


def test_injection_default_scope_has_versioned_parameter_provenance(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(context, {})

    assert plan.process == "injection"
    assert plan.scope_id == "injection.legacy-baseline"
    assert plan.scope_version == "1.1.0"
    assert plan.parameters["min_draft_deg"].value == 1.0
    assert plan.parameters["min_draft_deg"].source == "injection_legacy_default"
    assert plan.parameters["min_draft_deg"].unit == "degree"
    assert plan.operations[0].operation == "load_step"


def test_confirmed_parameter_override_is_normalized_and_traced(context):
    adapter = build_default_process_registry().get("injection")

    plan = adapter.compile(
        context,
        {
            "min_wall_mm": {"value": "1.6", "source": "project_fact"},
            "pull_dir": {"value": [0, 1, 0], "source": "user_confirmed"},
        },
    )

    assert plan.parameters["min_wall_mm"].value == 1.6
    assert plan.parameters["min_wall_mm"].source == "project_fact"
    assert plan.parameters["pull_dir"].value == [0.0, 1.0, 0.0]
    assert plan.parameters["pull_dir"].source == "user_confirmed"


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
