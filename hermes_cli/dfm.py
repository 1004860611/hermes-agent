"""Operator-facing diagnostics for the built-in DFM capability."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from tools.dfm.analyzers.base import AnalyzerContext
from tools.dfm.analyzers.registry import build_default_registry
from tools.dfm.config import load_dfm_config
from tools.dfm.errors import DFMError
from tools.dfm.project.workspace import DFMWorkspace


def build_parser(subparsers):
    parser = subparsers.add_parser("dfm", help="DFM capability diagnostics")
    actions = parser.add_subparsers(dest="dfm_action", required=True)
    doctor = actions.add_parser("doctor", help="Check DFM config, workspace, and analyzers")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def collect_diagnostics() -> dict:
    try:
        config = load_dfm_config()
        config_report = {"valid": True, "values": {
            "runtime_python": config.runtime_python,
            "max_concurrent_runs": config.max_concurrent_runs,
            "timeout_seconds": config.timeout_seconds,
            "max_file_size_mb": config.max_file_size_mb,
            "max_pages": config.max_pages,
        }}
    except DFMError as exc:
        config_report = {"valid": False, "error": exc.to_dict()["error"]}

    workspace = DFMWorkspace()
    writable = False
    write_error = None
    probe: Path | None = None
    try:
        workspace.root.mkdir(parents=True, exist_ok=True)
        probe = workspace.root / f".doctor-{uuid4().hex}.tmp"
        probe.write_text("ok", encoding="utf-8")
        writable = probe.read_text(encoding="utf-8") == "ok"
    except OSError as exc:
        write_error = type(exc).__name__
    finally:
        if probe is not None:
            probe.unlink(missing_ok=True)

    context = AnalyzerContext("doctor", workspace.root, None, [])
    registry = build_default_registry()
    capabilities = {key: registry.get(key).capability(context).to_dict() for key in registry.keys()}
    return {
        "ok": bool(config_report["valid"] and writable),
        "config": config_report,
        "workspace": {"path": str(workspace.root), "writable": writable, "error": write_error},
        "capabilities": capabilities,
        "note": "Diagnostics never install CAD, OCR, or system dependencies.",
    }


def dfm_command(args) -> int:
    if getattr(args, "dfm_action", None) != "doctor":
        return 2
    report = collect_diagnostics()
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"DFM workspace: {report['workspace']['path']}")
        print(f"Workspace writable: {report['workspace']['writable']}")
        print(f"Config valid: {report['config']['valid']}")
        for key, capability in report["capabilities"].items():
            print(f"{key}: {capability['status']} - {capability['reason']}")
    return 0 if report["ok"] else 1
