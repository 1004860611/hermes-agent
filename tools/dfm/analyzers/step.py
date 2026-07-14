"""M0 STEP adapter boundary; real Django-derived worker arrives in M1."""

from ..contracts import Capability, CapabilityStatus
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


class StepAnalyzer:
    key = "step"
    version = "m0-unavailable"
    supported_inputs = ("step", "fusion")

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.DEPENDENCY_MISSING,
            "The production STEP analyzer is not configured in this M0 foundation.",
            "dependency_missing",
            {"next_milestone": "M1"},
        )

    def run(self, context: AnalyzerContext, cancellation: CancellationToken):
        cancellation.raise_if_cancelled()
        capability = self.capability(context)
        raise DFMError(capability.error_code or "dependency_missing", capability.reason, capability.details)
