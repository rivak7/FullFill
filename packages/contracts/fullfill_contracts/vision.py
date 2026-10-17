"""Provider-neutral vision types. Python image inputs never go into UI responses."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .common import Contract, Identifier, PositiveQuantity, Quantity
from .orders import VerificationMode


class VerificationTarget(Contract):
    target_id: Identifier
    line_ids: list[Identifier] = Field(min_length=1)
    item_id: Identifier
    name: str
    expected_quantity: PositiveQuantity
    verification_mode: VerificationMode = "visible_item"
    label_aliases: list[str] = Field(default_factory=list)


class TargetObservation(Contract):
    target_id: Identifier
    status: Literal["present", "missing", "unsure"]
    observed_quantity: Quantity | None = None
    reason: str | None = None
    label_text: str | None = None


class UnexpectedItem(Contract):
    name: str
    quantity: PositiveQuantity | None = None


class ProviderMetadata(Contract):
    provider: str
    model: str
    prompt_version: str
    latency_ms: int = Field(ge=0, strict=True)
    request_id: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class Observations(Contract):
    schema_version: Literal[1] = 1
    capture_id: Identifier
    targets: list[TargetObservation] = Field(min_length=1)
    unexpected_items: list[UnexpectedItem] = Field(default_factory=list)
    scene_uncertainty: str | None = None
    provider: ProviderMetadata | None = None


@dataclass(frozen=True)
class ImageInput:
    data: bytes
    media_type: str


@dataclass(frozen=True)
class ReferenceImage:
    item_id: str
    revision: int
    image: ImageInput


@dataclass(frozen=True)
class VisionInput:
    capture_id: str
    image: ImageInput
    targets: tuple[VerificationTarget, ...]
    references: tuple[ReferenceImage, ...]
