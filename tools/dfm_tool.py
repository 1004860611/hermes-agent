"""Thin Hermes registration adapter for the built-in DFM capability."""

import json

from tools.dfm.errors import DFMError
from tools.dfm.service import get_dfm_service
from tools.registry import registry


def _call(kind: str, args: dict, **context) -> str:
    try:
        service = get_dfm_service()
        params = {key: value for key, value in args.items() if key != "action"}
        if kind == "project" and args.get("action") == "add_input":
            from tools.terminal_tool import resolve_task_overrides

            working_dir = resolve_task_overrides(context.get("task_id")).get("cwd")
            if working_dir:
                params["working_dir"] = working_dir
        if kind == "analysis" and args.get("action") == "start":
            params["_tool_progress_callback"] = context.get("tool_progress_callback")
            params["_tool_call_id"] = context.get("tool_call_id")
        result = service.project(args.get("action", ""), **params) if kind == "project" else service.analysis(args.get("action", ""), **params)
        return json.dumps(result, ensure_ascii=False)
    except DFMError as exc:
        return json.dumps(exc.to_dict(), ensure_ascii=False)


DFM_PROJECT_SCHEMA = {
    "name": "dfm_project",
    "description": "Manage durable DFM projects and register STEP or drawing inputs. Use status before analysis to inspect capabilities.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["create", "add_input", "status", "confirm_fact", "list"]},
        "project_id": {"type": "string"}, "name": {"type": "string"},
        "path": {"type": "string", "description": "Local path or Desktop @file: reference"},
        "fact_name": {"type": "string"}, "fact_value": {}, "idempotency_key": {"type": "string"},
    }, "required": ["action"]},
}

DFM_ANALYSIS_SCHEMA = {
    "name": "dfm_analysis",
    "description": "Plan and manage non-blocking DFM runs. Unavailable analyzers fail explicitly; never infer engineering findings from that status.",
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["plan", "start", "status", "cancel", "result"]},
        "project_id": {"type": "string"}, "plan_id": {"type": "string"}, "run_id": {"type": "string"},
        "base_plan_id": {"type": "string", "description": "Invalidated plan to rebuild with only affected operations."},
        "analyzer_key": {"type": "string", "enum": ["step", "drawing", "fusion"]},
        "idempotency_key": {"type": "string"},
    }, "required": ["action", "project_id"]},
}

registry.register(name="dfm_project", toolset="dfm", schema=DFM_PROJECT_SCHEMA, handler=lambda args, **kwargs: _call("project", args, **kwargs), emoji="🏭")
registry.register(name="dfm_analysis", toolset="dfm", schema=DFM_ANALYSIS_SCHEMA, handler=lambda args, **kwargs: _call("analysis", args, **kwargs), emoji="📐")
