from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.dfm.contracts import PlanOperation
from tools.dfm.errors import DFMError
from tools.dfm.ontology import LocalOntologyStore


PACKAGE_PATH = (
    Path(__file__).parents[3]
    / "tools"
    / "dfm"
    / "scopes"
    / "injection"
    / "ontology_snapshot_v1.json"
)


def _package():
    return json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))


def _rehash(payload):
    normalized = deepcopy(payload)
    normalized.pop("content_sha256", None)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload["content_sha256"] = hashlib.sha256(encoded).hexdigest()


def _operations():
    return [
        PlanOperation(
            "geometry.wall_thickness",
            "measure_wall_thickness",
            metric_ids=["injection.geometry.wall_thickness"],
            required_quantities=["thickness_mm"],
        ),
        PlanOperation(
            "geometry.draft",
            "measure_draft",
            metric_ids=["injection.geometry.draft"],
            required_quantities=["draft_angle_deg"],
        ),
    ]


def test_published_package_is_installed_as_a_local_sqlite_snapshot(tmp_path):
    database = tmp_path / "runtime" / "dfm-ontology.sqlite3"
    store = LocalOntologyStore.from_package(PACKAGE_PATH, database_path=database)

    identity = store.identity()
    context = store.check_context("check.main_wall_minimum_thickness")

    assert database.is_file()
    assert identity.snapshot_id == "ontology.injection.default@1.0.0"
    assert len(identity.content_sha256) == 64
    assert context["check"]["definition"]
    assert {item["predicate"] for item in context["relations"]} >= {
        "APPLIES_TO_FEATURE",
        "USES_OPERAND",
        "REQUIRES_FACTOR",
    }
    assert context["factor_options"][0]["option_code"] == "ABS"


def test_bundled_ontology_publication_matches_its_json_schema():
    schema_path = (
        Path(__file__).parents[3]
        / "tools"
        / "dfm"
        / "schemas"
        / "ontology_snapshot.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    payload = json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(payload)


def test_ontology_compiler_emits_existing_generic_rule_contract():
    store = LocalOntologyStore.from_package(PACKAGE_PATH)

    compiled = store.compile(
        "injection",
        {"material": "ABS", "model_units": "mm", "pull_dir": [0, 0, 1]},
        _operations(),
    )

    wall = next(
        item
        for item in compiled.rule_bindings
        if item.check_id == "check.main_wall_minimum_thickness"
    )
    assert compiled.rules[wall.rule_id].value == 1.2
    assert wall.metric_id == "injection.geometry.wall_thickness"
    assert wall.expression == {"operand": "actual"}
    assert compiled.binding_selectors[wall.binding_id]["actual"] == {
        "feature_type_id": "feature.ordinary_part",
        "region_type_id": "region.ordinary",
        "feature_kind": "ordinary_part",
        "region_role": "ordinary",
    }


def test_republished_rule_changes_threshold_without_runtime_code_change(tmp_path):
    store = LocalOntologyStore(tmp_path / "dfm-ontology.sqlite3")
    first = _package()
    store.install_package(first)
    initial = store.compile("injection", {"material": "ABS"}, _operations())

    second = deepcopy(first)
    second["snapshot_id"] = "ontology.injection.default@1.1.0"
    second["ontology_version"] = "1.1.0"
    second["rule_set"]["version"] = "1.1.0"
    wall = second["rules"][0]
    wall["rule_version_id"] = "rule-version.main-wall-min-abs.2"
    wall["version"] = "1.1.0"
    wall["threshold"] = 1.5
    _rehash(second)
    store.install_package(second)
    updated = store.compile("injection", {"material": "ABS"}, _operations())

    assert initial.rules["R_INJ_MAIN_WALL_MIN_ABS"].value == 1.2
    assert updated.rules["R_INJ_MAIN_WALL_MIN_ABS"].value == 1.5
    assert updated.identity.rule_set_version == "1.1.0"


def test_new_feature_check_compiles_from_ontology_and_worker_capability_only():
    payload = _package()
    payload["concepts"].extend([
        {
            "concept_id": "feature.screw_boss",
            "concept_type": "feature_type",
            "name_zh": "螺钉柱",
            "definition": "用于螺钉连接的柱状注塑特征。",
            "aliases": [],
            "properties": {"worker_kind": "screw_boss"},
            "status": "active",
        },
        {
            "concept_id": "region.screw_boss.wall",
            "concept_type": "region_type",
            "name_zh": "螺钉柱柱壁",
            "definition": "螺钉柱参与壁厚计算的柱壁区域。",
            "aliases": [],
            "properties": {"worker_role": "wall"},
            "status": "active",
        },
        {
            "concept_id": "check.screw_boss.minimum_wall",
            "concept_type": "check",
            "name_zh": "螺钉柱最小柱壁",
            "definition": "判断螺钉柱柱壁最小厚度。",
            "aliases": [],
            "properties": {},
            "status": "active",
        },
    ])
    payload["relations"].extend([
        {
            "relation_id": "rel.process.injection.check.screw-boss-wall",
            "subject_id": "process.injection",
            "predicate": "HAS_CHECK",
            "object_id": "check.screw_boss.minimum_wall",
            "qualifiers": {},
            "sort_order": 30,
        },
        {
            "relation_id": "rel.feature.screw-boss.region.wall",
            "subject_id": "feature.screw_boss",
            "predicate": "HAS_REGION",
            "object_id": "region.screw_boss.wall",
            "qualifiers": {},
            "sort_order": 10,
        },
        {
            "relation_id": "rel.check.screw-boss-wall.feature",
            "subject_id": "check.screw_boss.minimum_wall",
            "predicate": "APPLIES_TO_FEATURE",
            "object_id": "feature.screw_boss",
            "qualifiers": {},
            "sort_order": 10,
        },
        {
            "relation_id": "rel.check.screw-boss-wall.operand.actual",
            "subject_id": "check.screw_boss.minimum_wall",
            "predicate": "USES_OPERAND",
            "object_id": "metric.injection.wall_thickness",
            "qualifiers": {
                "alias": "actual",
                "worker_metric_id": "injection.geometry.wall_thickness",
                "quantity_id": "thickness_mm",
                "aggregation": "minimum",
                "feature_type_id": "feature.screw_boss",
                "region_type_id": "region.screw_boss.wall",
                "feature_kind": "screw_boss",
                "region_role": "wall",
                "required": True,
            },
            "sort_order": 20,
        },
    ])
    payload["rules"].append({
        "rule_version_id": "rule-version.screw-boss-wall.1",
        "rule_id": "R_INJ_SCREW_BOSS_WALL_MIN",
        "version": "1.0.0",
        "check_id": "check.screw_boss.minimum_wall",
        "name": "螺钉柱最小柱壁",
        "conditions": [],
        "expression": {"operand": "actual"},
        "comparator": "GTE",
        "threshold": 1.0,
        "result_unit": "mm",
        "severity": "warning",
        "priority": 0,
        "is_default": True,
        "status": "released",
        "citation_refs": [],
    })
    _rehash(payload)
    store = LocalOntologyStore.from_package(payload)

    compiled = store.compile("injection", {"material": "ABS"}, _operations())
    binding = next(
        item
        for item in compiled.rule_bindings
        if item.check_id == "check.screw_boss.minimum_wall"
    )

    assert binding.metric_id == "injection.geometry.wall_thickness"
    assert compiled.rules[binding.rule_id].value == 1.0
    assert (
        compiled.binding_selectors[binding.binding_id]["actual"]["feature_kind"]
        == "screw_boss"
    )
    assert any(
        item["feature_kind"] == "screw_boss"
        and item["region_role"] == "wall"
        and item["metrics"] == ["injection.geometry.wall_thickness"]
        for item in store.analysis_target_specs("injection")
    )


def test_ontology_check_rejects_an_operand_absent_from_worker_capability():
    store = LocalOntologyStore.from_package(PACKAGE_PATH)

    with pytest.raises(DFMError) as exc_info:
        store.compile("injection", {"material": "ABS"}, [])

    assert exc_info.value.code == "ontology_capability_mismatch"


def test_declared_publication_hash_is_verified():
    payload = _package()
    payload["content_sha256"] = "0" * 64

    with pytest.raises(DFMError) as exc_info:
        LocalOntologyStore.from_package(payload)

    assert exc_info.value.code == "ontology_snapshot_invalid"
