"""Explicit unavailable boundary for drawing analysis."""

from ..contracts import Capability, CapabilityStatus
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


class DrawingAnalyzer:
    key = "drawing"
    version = "m0-unavailable"
    supported_inputs = ("drawing", "fusion")

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.NOT_IMPLEMENTED,
            "Drawing analysis is not implemented in M0.",
            "unsupported_capability",
            {"next_milestone": "M3"},
        )

    def run(self, context: AnalyzerContext, cancellation: CancellationToken):
        cancellation.raise_if_cancelled()
        capability = self.capability(context)
        raise DFMError("unsupported_capability", capability.reason, capability.details)
