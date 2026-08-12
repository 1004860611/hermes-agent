"""Explicit M2.6 placeholder boundary for observation/feature fusion."""

from ..contracts import Capability, CapabilityStatus
from ..errors import DFMError
from .base import AnalyzerContext, CancellationToken


class FusionAnalyzer:
    key = "fusion"
    version = "m26-fusion-placeholder"
    supported_inputs = ("fusion",)

    def capability(self, context: AnalyzerContext) -> Capability:
        return Capability(
            self.key,
            CapabilityStatus.NOT_IMPLEMENTED,
            "Observation-to-feature fusion is not implemented yet.",
            "unsupported_capability",
            {
                "next_milestone": "M2.6 minimal / M5 generalization",
                "input_contracts": [
                    "ObservationRecord[]",
                    "FeatureRecord[]",
                    "RegionRecord[]",
                ],
                "output_contracts": [
                    "FusionLinkRecord[]",
                    "DiscoverySnapshotRecord",
                ],
            },
        )

    def run(self, context: AnalyzerContext, cancellation: CancellationToken):
        cancellation.raise_if_cancelled()
        capability = self.capability(context)
        raise DFMError("unsupported_capability", capability.reason, capability.details)
