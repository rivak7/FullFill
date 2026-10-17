"""Test-double slot; intentionally does not invent a successful vision result."""

from fullfill_contracts.ports import VisionProvider
from fullfill_contracts.vision import Observations, VisionInput


class FakeVision(VisionProvider):
    async def inspect(self, request: VisionInput) -> Observations:
        raise NotImplementedError(
            "Implement deterministic fixture responses for local development."
        )
