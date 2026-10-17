"""Perceptron integration slot; no calls, prompts, or existing vision code are replaced."""

from fullfill_contracts.ports import VisionProvider
from fullfill_contracts.vision import Observations, VisionInput


class PerceptronVision(VisionProvider):
    async def inspect(self, request: VisionInput) -> Observations:
        """Wrap the team's Perceptron implementation behind this stable signature."""
        raise NotImplementedError("Connect the team's Perceptron implementation here.")
