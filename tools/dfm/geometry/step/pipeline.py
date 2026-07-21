"""Versioned operation validation and check-family selection for STEP M1.2."""

from __future__ import annotations

from ...contracts import PlanOperation
from ...errors import DFMError


OPERATION_CHECK_FAMILIES = {
    "load_step": "load",
    "inspect_topology": "topology",
    "inspect_small_features": "small_features",
    "measure_planar_spacing": "planar_spacing",
    "inspect_face_quality": "face_quality",
    "inspect_cylindrical_features": "cylindrical",
    "measure_wall_thickness": "thickness",
    "measure_draft": "draft",
    "inspect_surface_continuity": "continuity",
    "inspect_undercut": "undercut",
    "render_evidence": "evidence",
}


def validate_operations(operations: list[PlanOperation]) -> list[str]:
    if not operations:
        raise DFMError(
            "worker_request_invalid",
            "The STEP worker requires persisted plan operations.",
        )
    ids: set[str] = set()
    ordered: list[str] = []
    for item in operations:
        if item.operation_id in ids:
            raise DFMError(
                "worker_request_invalid",
                "DFM plan operation ids must be unique.",
                {"operation_id": item.operation_id},
            )
        if item.operation not in OPERATION_CHECK_FAMILIES:
            raise DFMError(
                "unsupported_capability",
                "The DFM plan contains an unsupported STEP operation.",
                {"operation": item.operation},
            )
        missing = [
            dependency for dependency in item.depends_on if dependency not in ids
        ]
        if missing:
            raise DFMError(
                "worker_request_invalid",
                "DFM plan operations must be dependency ordered.",
                {"operation_id": item.operation_id, "missing_dependencies": missing},
            )
        ids.add(item.operation_id)
        ordered.append(item.operation)
    if ordered[0] != "load_step" or "inspect_topology" not in ordered:
        raise DFMError(
            "worker_request_invalid",
            "STEP plans must load the model and inspect topology first.",
        )
    return ordered
