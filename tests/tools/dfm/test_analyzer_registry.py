from pathlib import Path

import pytest

from tools.dfm.analyzers.base import AnalyzerContext, CancellationToken
from tools.dfm.analyzers.registry import AnalyzerRegistry, build_default_registry
from tools.dfm.contracts import CapabilityStatus
from tools.dfm.config import DFMConfig
from tools.dfm.errors import DFMError


class AvailableAnalyzer:
    key = "test"
    version = "1"
    supported_inputs = ("step",)

    def capability(self, context):
        from tools.dfm.contracts import Capability

        return Capability(self.key, CapabilityStatus.AVAILABLE, "test analyzer")

    def run(self, context, cancellation):
        cancellation.raise_if_cancelled()
        return []


def _context(tmp_path):
    return AnalyzerContext("dfm_123", Path(tmp_path), "step", [])


def test_registry_rejects_duplicates_and_returns_deterministic_keys(tmp_path):
    registry = AnalyzerRegistry()
    registry.register(AvailableAnalyzer())

    with pytest.raises(DFMError) as exc_info:
        registry.register(AvailableAnalyzer())

    assert exc_info.value.code == "analyzer_duplicate"
    assert registry.keys() == ["test"]
    assert registry.get("test").capability(_context(tmp_path)).status is CapabilityStatus.AVAILABLE


def test_default_registry_exposes_geometry_and_document_boundaries(tmp_path):
    registry = build_default_registry()
    context = _context(tmp_path)

    capabilities = {key: registry.get(key).capability(context) for key in registry.keys()}

    assert registry.keys() == ["drawing", "fusion", "occt"]
    assert capabilities["occt"].status in {
        CapabilityStatus.AVAILABLE,
        CapabilityStatus.DEPENDENCY_MISSING,
    }
    assert capabilities["drawing"].status is CapabilityStatus.NOT_IMPLEMENTED
    assert capabilities["fusion"].status is CapabilityStatus.NOT_IMPLEMENTED
    assert capabilities["drawing"].error_code == "unsupported_capability"


def test_default_registry_propagates_runtime_configuration(monkeypatch):
    monkeypatch.setattr(
        "tools.dfm.analyzers.registry.discover_geometry_executable",
        lambda configured: "C:/dfm/dfm-geometry.exe",
    )
    config = DFMConfig(
        geometry_executable="C:/dfm/dfm-geometry.exe",
        geometry_timeout_seconds=123,
    )

    analyzer = build_default_registry(config).get("occt")

    assert analyzer.executable == "C:/dfm/dfm-geometry.exe"
    assert analyzer.timeout_seconds == 123


@pytest.mark.parametrize("key", ["drawing", "fusion"])
def test_unavailable_production_analyzers_never_emit_placeholder_results(tmp_path, key):
    analyzer = build_default_registry().get(key)

    with pytest.raises(DFMError) as exc_info:
        analyzer.run(_context(tmp_path), CancellationToken())

    assert exc_info.value.code in {"dependency_missing", "unsupported_capability"}


def test_occt_analyzer_requires_native_engine(tmp_path):
    analyzer = build_default_registry().get("occt")

    with pytest.raises(DFMError) as exc_info:
        analyzer.run(_context(tmp_path), CancellationToken())

    assert exc_info.value.code in {"plan_required", "geometry_engine_missing"}


def test_cancellation_token_is_cooperative():
    token = CancellationToken()
    token.cancel()

    with pytest.raises(DFMError) as exc_info:
        token.raise_if_cancelled()

    assert exc_info.value.code == "run_cancelled"
