"""Validated, profile-aware configuration for the built-in DFM capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import DFMError


@dataclass(frozen=True)
class DFMConfig:
    runtime_python: str = "auto"
    default_process: str = "injection_molding"
    max_concurrent_runs: int = 1
    timeout_seconds: int = 900
    max_file_size_mb: int = 200
    max_pages: int = 50
    keep_failed_runs: bool = True


def _nested(mapping: Mapping[str, Any], *keys: str, default: Any) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def _positive_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DFMError("config_invalid", f"{path} must be a positive integer.", {"path": path})
    return value


def load_dfm_config(config: Mapping[str, Any] | None = None) -> DFMConfig:
    if config is None:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly()
    defaults = DFMConfig()
    runtime_python = _nested(config, "dfm", "runtime", "python", default=defaults.runtime_python)
    default_process = _nested(config, "dfm", "defaults", "process", default=defaults.default_process)
    keep_failed = _nested(
        config, "dfm", "retention", "keep_failed_runs", default=defaults.keep_failed_runs
    )
    if not isinstance(runtime_python, str) or not runtime_python.strip():
        raise DFMError("config_invalid", "dfm.runtime.python must be a non-empty string.")
    if not isinstance(default_process, str) or not default_process.strip():
        raise DFMError("config_invalid", "dfm.defaults.process must be a non-empty string.")
    if not isinstance(keep_failed, bool):
        raise DFMError("config_invalid", "dfm.retention.keep_failed_runs must be boolean.")
    return DFMConfig(
        runtime_python=runtime_python.strip(),
        default_process=default_process.strip(),
        max_concurrent_runs=_positive_int(
            _nested(config, "dfm", "runtime", "max_concurrent_runs", default=defaults.max_concurrent_runs),
            "dfm.runtime.max_concurrent_runs",
        ),
        timeout_seconds=_positive_int(
            _nested(config, "dfm", "runtime", "timeout_seconds", default=defaults.timeout_seconds),
            "dfm.runtime.timeout_seconds",
        ),
        max_file_size_mb=_positive_int(
            _nested(config, "dfm", "intake", "max_file_size_mb", default=defaults.max_file_size_mb),
            "dfm.intake.max_file_size_mb",
        ),
        max_pages=_positive_int(
            _nested(config, "dfm", "intake", "max_pages", default=defaults.max_pages),
            "dfm.intake.max_pages",
        ),
        keep_failed_runs=keep_failed,
    )
