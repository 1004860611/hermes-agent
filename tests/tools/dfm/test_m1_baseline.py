from pathlib import Path

import pytest

from tests.tools.dfm.baseline import (
    comparable_issue_metrics,
    issue_relationships,
    legacy_source_path,
    occ_available,
    run_hermes_worker,
    run_legacy,
)


FIXTURE_DIR = Path("tests/fixtures/dfm/step")
FIXTURE = FIXTURE_DIR / "injection_plate_with_hole.step"
PROFILE = FIXTURE_DIR / "injection_legacy_profile.json"


@pytest.mark.skipif(not occ_available(), reason="real M1 baseline requires pythonocc-core")
def test_legacy_and_hermes_measurements_are_equivalent(tmp_path):
    legacy_source = legacy_source_path()
    if not legacy_source.is_file():
        pytest.skip(f"legacy Django analyzer is unavailable: {legacy_source}")

    old = run_legacy(legacy_source, FIXTURE, PROFILE, tmp_path / "legacy")
    new = run_hermes_worker(FIXTURE, PROFILE, tmp_path / "hermes")

    assert new["stats"]["valid_brep"] == old["stats"]["valid_brep"]
    assert new["stats"]["bbox_size_mm"] == pytest.approx(
        old["stats"]["bbox_size_mm"], abs=0.01
    )
    assert issue_relationships(new) == issue_relationships(old)
    assert comparable_issue_metrics(new) == pytest.approx(
        comparable_issue_metrics(old), rel=1e-5, abs=1e-4
    )
