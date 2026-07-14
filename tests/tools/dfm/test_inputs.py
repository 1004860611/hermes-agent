from pathlib import Path
from types import SimpleNamespace

import pytest

from hermes_constants import reset_hermes_home_override, set_hermes_home_override
from tools.dfm.config import DFMConfig
from tools.dfm.errors import DFMError
from tools.dfm.project.inputs import InputRegistrar
from tools.dfm.project.manifest import ManifestStore
from tools.dfm.project.workspace import DFMWorkspace


@pytest.fixture
def project(tmp_path):
    token = set_hermes_home_override(tmp_path / "home")
    workspace = DFMWorkspace()
    manifest = workspace.create_project("Bracket")
    try:
        yield workspace, manifest.project_id, tmp_path
    finally:
        reset_hermes_home_override(token)


@pytest.mark.parametrize(("suffix", "kind"), [(".step", "step"), (".stp", "step"), (".pdf", "drawing"), (".png", "drawing"), (".jpg", "drawing"), (".jpeg", "drawing")])
def test_registers_supported_input_with_hash_and_safe_relative_path(project, suffix, kind):
    workspace, project_id, temp = project
    source = temp / f"part{suffix}"
    source.write_bytes(b"synthetic-dfm-input")

    record = InputRegistrar(workspace, DFMConfig()).register(project_id, source)

    assert record.kind == kind
    assert len(record.sha256) == 64
    assert record.relative_path.startswith("inputs/")
    assert (workspace.project_dir(project_id) / record.relative_path).read_bytes() == source.read_bytes()


def test_project_mode_becomes_fusion_and_duplicate_content_is_idempotent(project):
    workspace, project_id, temp = project
    step = temp / "part.step"
    drawing = temp / "drawing.pdf"
    duplicate = temp / "renamed.step"
    step.write_bytes(b"step")
    drawing.write_bytes(b"drawing")
    duplicate.write_bytes(b"step")
    registrar = InputRegistrar(workspace, DFMConfig())

    first = registrar.register(project_id, step)
    registrar.register(project_id, drawing)
    again = registrar.register(project_id, duplicate)
    manifest = ManifestStore(workspace.project_dir(project_id)).load()

    assert again.input_id == first.input_id
    assert len(manifest.inputs) == 2
    assert manifest.input_mode == "fusion"


def test_rejects_missing_unsupported_and_oversized_inputs(project):
    workspace, project_id, temp = project
    registrar = InputRegistrar(workspace, DFMConfig(max_file_size_mb=1))
    unsupported = temp / "part.exe"
    unsupported.write_bytes(b"x")
    oversized = temp / "large.step"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(DFMError, match="does not exist") as missing:
        registrar.register(project_id, temp / "missing.step")
    assert missing.value.code == "input_not_found"
    with pytest.raises(DFMError) as bad_type:
        registrar.register(project_id, unsupported)
    assert bad_type.value.code == "input_type_unsupported"
    with pytest.raises(DFMError) as too_large:
        registrar.register(project_id, oversized)
    assert too_large.value.code == "input_too_large"


def test_source_name_cannot_control_destination_path(project):
    workspace, project_id, temp = project
    outside = temp / "nested" / "part.step"
    outside.parent.mkdir()
    outside.write_bytes(b"step")

    record = InputRegistrar(workspace, DFMConfig()).register(project_id, Path(outside))

    assert ".." not in record.relative_path
    assert "/nested/" not in record.relative_path


def test_same_bytes_with_different_engineering_kind_are_distinct(project):
    workspace, project_id, temp = project
    step = temp / "part.step"
    drawing = temp / "drawing.pdf"
    step.write_bytes(b"same-opaque-bytes")
    drawing.write_bytes(b"same-opaque-bytes")
    registrar = InputRegistrar(workspace, DFMConfig())

    step_record = registrar.register(project_id, step)
    drawing_record = registrar.register(project_id, drawing)
    manifest = ManifestStore(workspace.project_dir(project_id)).load()

    assert step_record.input_id != drawing_record.input_id
    assert len(manifest.inputs) == 2
    assert manifest.input_mode == "fusion"


def test_streaming_copy_enforces_limit_even_if_initial_stat_is_stale(project, monkeypatch):
    workspace, project_id, temp = project
    source = temp / "growing.step"
    source.write_bytes(b"x" * (1024 * 1024 + 1))
    original_stat = Path.stat

    def stale_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == source:
            return SimpleNamespace(st_mode=result.st_mode, st_size=1)
        return result

    monkeypatch.setattr(Path, "stat", stale_stat)

    with pytest.raises(DFMError) as exc_info:
        InputRegistrar(workspace, DFMConfig(max_file_size_mb=1)).register(project_id, source)

    assert exc_info.value.code == "input_too_large"
