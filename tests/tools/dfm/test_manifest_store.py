import json
from dataclasses import replace

import pytest

from tools.dfm.contracts import ProjectManifest
from tools.dfm.errors import DFMError
from tools.dfm.project.manifest import ManifestStore


def _manifest() -> ProjectManifest:
    return ProjectManifest(
        project_id="dfm_123",
        name="Bracket",
        created_at="2026-07-13T10:00:00Z",
        updated_at="2026-07-13T10:00:00Z",
    )


def test_manifest_store_round_trips_and_leaves_no_temp_file(tmp_path):
    store = ManifestStore(tmp_path)

    store.save(_manifest())

    assert store.load() == _manifest()
    assert json.loads(store.path.read_text(encoding="utf-8"))["project_id"] == "dfm_123"
    assert list(tmp_path.glob("*.tmp")) == []


def test_manifest_store_rejects_malformed_json(tmp_path):
    store = ManifestStore(tmp_path)
    store.path.write_text("{broken", encoding="utf-8")

    with pytest.raises(DFMError) as exc_info:
        store.load()

    assert exc_info.value.code == "manifest_invalid"


def test_manifest_store_rejects_unknown_schema_version(tmp_path):
    store = ManifestStore(tmp_path)
    payload = _manifest().to_dict()
    payload["schema_version"] = 99
    store.path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DFMError) as exc_info:
        store.load()

    assert exc_info.value.code == "manifest_version_unsupported"


def test_manifest_update_increments_revision_and_rejects_stale_writer(tmp_path):
    store = ManifestStore(tmp_path)
    store.save(_manifest())

    updated = store.update(
        lambda current: replace(current, name="Bracket v2"),
        expected_revision=0,
    )

    assert updated.revision == 1
    assert store.load().name == "Bracket v2"
    with pytest.raises(DFMError) as exc_info:
        store.update(lambda current: current, expected_revision=0)
    assert exc_info.value.code == "manifest_conflict"
