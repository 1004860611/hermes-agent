import hashlib
import json

from tools.dfm.contracts import (
    ArtifactRecord,
    EffectiveRule,
    PlanOperation,
    PlanRecord,
    ResolvedArgument,
)
from tools.dfm.runtime.objective_cache import (
    ObjectiveOperationCache,
    operation_fingerprints,
)


def _plan(*, rule=1.0, pull=(0, 0, 1)):
    return PlanRecord(
        "plan_1",
        "step",
        ["occt"],
        "ready",
        "now",
        process="injection",
        scope_id="injection.geometry-core",
        scope_version="4.0.0",
        input_ids=["input_1"],
        input_hashes={"input_1": "a" * 64},
        rules={"min_draft_deg": EffectiveRule(rule, "degree", "scope")},
        operations=[
            PlanOperation("geometry.preflight", "geometry_preflight"),
            PlanOperation(
                "topology.index", "index_topology", ["geometry.preflight"]
            ),
            PlanOperation(
                "topology.aag", "build_aag", ["topology.index"]
            ),
            PlanOperation(
                "measure_draft",
                "measure_draft",
                ["topology.aag"],
                ["injection.geometry.draft"],
                ["draft_angle_deg"],
                arguments={
                    "pull_direction": ResolvedArgument(list(pull), "fact:pull_dir")
                },
            ),
        ],
    )


def test_operation_fingerprint_ignores_hermes_rule_but_tracks_geometry_arguments():
    common = {
        "input_sha256": "a" * 64,
        "analyzer_key": "occt",
        "analyzer_version": "occt-dfm-geometry-1.0.0",
    }

    baseline = operation_fingerprints(_plan(), **common)
    changed_rule = operation_fingerprints(_plan(rule=2.0), **common)
    changed_pull = operation_fingerprints(_plan(pull=(0, 1, 0)), **common)

    assert baseline == changed_rule
    assert baseline["geometry.preflight"] == changed_pull["geometry.preflight"]
    assert baseline["topology.index"] == changed_pull["topology.index"]
    assert baseline["topology.aag"] == changed_pull["topology.aag"]
    assert baseline["measure_draft"] != changed_pull["measure_draft"]


def test_cache_restores_objective_checkpoint_into_new_run(tmp_path):
    source = tmp_path / "runs" / "run_old" / "artifacts" / "measurements.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": "run_old",
                "input_sha256": "a" * 64,
                "process": "injection",
                "scope_id": "injection.geometry-core",
                "producer_contract": "measurement_only",
                "measurements": [
                    {
                        "measurement_id": "measurement-draft",
                        "operation_id": "measure_draft",
                        "calculator_id": "measure_draft",
                        "metric_id": "injection.geometry.draft",
                        "quantity_id": "draft_angle_deg",
                        "input_sha256": "a" * 64,
                        "geometry_refs": [],
                        "field_refs": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    content = source.read_bytes()
    artifact = ArtifactRecord(
        "measurements",
        "measurements",
        source.relative_to(tmp_path).as_posix(),
        "application/json",
        "now",
        run_id="run_old",
        logical_id="measurements",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    cache = ObjectiveOperationCache()
    common = {
        "input_sha256": "a" * 64,
        "analyzer_key": "occt",
        "analyzer_version": "occt-dfm-geometry-1.0.0",
    }

    cache.publish(tmp_path, "run_old", _plan(), [artifact], **common)
    restored = cache.restore(tmp_path, "run_new", _plan(rule=2.0), **common)

    assert restored is not None
    assert restored[0].run_id == "run_new"
    target = tmp_path / restored[0].relative_path
    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == "run_new"
    assert cache.restore(
        tmp_path, "run_changed", _plan(pull=(0, 1, 0)), **common
    ) is None
