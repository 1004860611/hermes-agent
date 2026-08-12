"""Explicit M2.6 placeholder boundary for drawing observations."""

from ..contracts import Capability, CapabilityStatus
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


class DrawingAnalyzer:
    key = "drawing"
    version = "m26-observation-placeholder"
    supported_inputs = ("drawing", "fusion")

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.NOT_IMPLEMENTED,
            "Drawing observation extraction is not implemented yet.",
            "unsupported_capability",
            {
                "next_milestone": "M3/M4",
                "output_contract": "ObservationRecord[]",
                "placeholder_pipeline": [
                    "render_pages",
                    "extract_native_text_or_ocr",
                    "detect_views_and_callouts",
                    "normalize_candidates",
                    "emit_observations",
                ],
            },
        )

    def run(self, context: AnalyzerContext, cancellation: CancellationToken):
        cancellation.raise_if_cancelled()
        capability = self.capability(context)
        raise DFMError("unsupported_capability", capability.reason, capability.details)
