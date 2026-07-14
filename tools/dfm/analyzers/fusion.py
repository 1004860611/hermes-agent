"""Explicit unavailable boundary for STEP/drawing fusion."""

from ..contracts import Capability, CapabilityStatus
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


class FusionAnalyzer:
    key = "fusion"
    version = "m0-unavailable"
    supported_inputs = ("fusion",)

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.NOT_IMPLEMENTED,
            "STEP/drawing fusion is not implemented in M0.",
            "unsupported_capability",
            {"next_milestone": "M5"},
        )

    def run(self, context: AnalyzerContext, cancellation: CancellationToken):
        cancellation.raise_if_cancelled()
        capability = self.capability(context)
        raise DFMError("unsupported_capability", capability.reason, capability.details)
