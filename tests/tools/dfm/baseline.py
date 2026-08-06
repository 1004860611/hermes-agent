"""Real-OCC comparison helpers for the M1 Django compatibility baseline."""

from __future__ import annotations

from collections import defaultdict
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from tools.dfm.analyzers.base import AnalyzerContext
from tools.dfm.contracts import (
    EffectiveRule,
    PlanOperation,
    WorkerRequest,
    WorkerResult,
)
from tools.dfm.runtime.events import parse_worker_event
from tools.dfm.processes.injection import InjectionProcessAdapter
from tools.dfm.workers.step_worker import WORKER_VERSION


ROOT = Path(__file__).resolve().parents[3]
SCOPE_PATH = ROOT / "tools" / "dfm" / "scopes" / "injection" / "legacy_baseline_v1.json"


def occ_available() -> bool:
    try:
        return importlib.util.find_spec("OCC") is not None
    except (ImportError, AttributeError, ValueError):
        return False


def legacy_source_path() -> Path:
    return (
        ROOT.parent
        / "django-vue3-admin"
        / "backend"
        / "aimold_app"
        / "agents"
        / "skill"
        / "dfm-analysis"
        / "scripts"
        / "dfm_analyze.py"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _diagnostics(legacy_source: Path | None = None) -> dict[str, Any]:
    details = {
        "platform": platform.platform(),
        "python": sys.executable,
        "python_version": platform.python_version(),
        "occ_available": occ_available(),
        "worker_version": WORKER_VERSION,
        "migrated_source_sha256": _sha256(
            ROOT / "tools" / "dfm" / "geometry" / "step" / "legacy_analyzer.py"
        ),
    }
    if legacy_source is not None and legacy_source.is_file():
        details["legacy_source"] = str(legacy_source)
        details["legacy_source_sha256"] = _sha256(legacy_source)
    return details


def _run(
    argv: list[str], cwd: Path, legacy_source: Path | None = None
) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        errors="replace",
        shell=False,
        timeout=900,
    )
    if completed.returncode != 0:
        raise AssertionError(
            json.dumps(
                {
                    "argv": argv,
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-4000:],
                    "stderr_tail": completed.stderr[-4000:],
                    "environment": _diagnostics(legacy_source),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return completed


def _profile(
    profile_path: Path,
) -> tuple[dict[str, Any], dict[str, EffectiveRule]]:
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scope = json.loads(SCOPE_PATH.read_text(encoding="utf-8"))
    expected = {key: item["value"] for key, item in scope["parameters"].items()}
    assert profile["process"] == scope["process"] == "injection"
    assert profile["version"] == scope["version"] == "1.1.0"
    assert profile["thresholds"] == expected
    rules = {
        key: EffectiveRule(
            value, scope["parameters"][key].get("unit"), "injection_legacy_default"
        )
        for key, value in expected.items()
        if scope["parameters"][key].get("kind") == "rule"
    }
    return profile, rules


def run_legacy(
    legacy_source: Path,
    fixture: Path,
    profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    _profile(profile_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            str(legacy_source.resolve()),
            str(fixture.resolve()),
            "--out",
            str(output_dir.resolve()),
            "--config",
            str(profile_path.resolve()),
            "--process",
            "injection",
            "--highlight-step-name",
            "dfm_highlighted.step",
        ],
        ROOT,
        legacy_source,
    )
    return json.loads((output_dir / "dfm_report.json").read_text(encoding="utf-8"))


def run_hermes_worker(
    fixture: Path,
    profile_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    profile, rules = _profile(profile_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    process_plan = InjectionProcessAdapter().compile(
        AnalyzerContext("baseline", output_dir.parent, "step", []), {}
    )
    request = WorkerRequest(
        schema_version=1,
        run_id="m1-baseline",
        input_path=str(fixture.resolve()),
        output_dir=str(output_dir.resolve()),
        process=profile["process"],
        scope_id="injection.legacy-baseline",
        analyzer_version=WORKER_VERSION,
        rules=rules,
        operations=process_plan.operations,
    )
    request_path = output_dir.parent / "worker_request.json"
    request_path.write_text(json.dumps(request.to_dict(), indent=2), encoding="utf-8")
    completed = _run(
        [
            sys.executable,
            "-m",
            "tools.dfm.workers.step_worker",
            "--request",
            str(request_path),
        ],
        ROOT,
    )
    events = [
        event
        for line in completed.stdout.splitlines()
        if (event := parse_worker_event(line)) is not None
    ]
    completed_events = [event for event in events if event.type == "completed"]
    assert len(completed_events) == 1, {
        "events": [event.to_dict() for event in events],
        "environment": _diagnostics(),
    }
    result = WorkerResult.from_dict(
        json.loads((output_dir / completed_events[0].path).read_text(encoding="utf-8"))
    )
    assert result.worker_version == WORKER_VERSION
    report = next(item for item in result.artifacts if item["kind"] == "report_json")
    return json.loads((output_dir / report["path"]).read_text(encoding="utf-8"))


def issue_relationships(report: dict[str, Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            issue["code"],
            issue["severity"],
            tuple(sorted(tuple(sorted(ref.items())) for ref in issue.get("refs", []))),
        )
        for issue in report["issues"]
    )


def comparable_issue_metrics(report: dict[str, Any]) -> dict[str, float]:
    counters: defaultdict[str, int] = defaultdict(int)
    result: dict[str, float] = {}
    for issue in sorted(report["issues"], key=lambda item: (item["code"], item["id"])):
        code = issue["code"]
        counters[code] += 1
        prefix = f"{code}[{counters[code]}]"
        _flatten_numbers(issue.get("metric", {}), prefix, result)
    return result


def _flatten_numbers(value: Any, prefix: str, result: dict[str, float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        result[prefix] = float(value)
    elif isinstance(value, dict):
        for key in sorted(value):
            if key == "render_checks":
                continue
            _flatten_numbers(value[key], f"{prefix}.{key}", result)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _flatten_numbers(item, f"{prefix}[{index}]", result)
