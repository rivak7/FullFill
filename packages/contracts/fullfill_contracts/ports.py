"""Interfaces usable by adapters and evaluation without importing the API app."""

from typing import Protocol

from .vision import ImageInput, Observations, VisionInput


class VisionProvider(Protocol):
    async def inspect(self, request: VisionInput) -> Observations: ...


class CaptureSource(Protocol):
    async def capture(self) -> ImageInput: ...

    async def close(self) -> None: ...
