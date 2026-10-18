"""Provider-neutral vision types. Python image inputs never go into UI responses."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

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


class BoundingBox(Contract):
    """Coordinates on the order image, normalized to a 0–1000 grid."""

    x_min: int = Field(ge=0, le=1000, strict=True)
    y_min: int = Field(ge=0, le=1000, strict=True)
    x_max: int = Field(ge=0, le=1000, strict=True)
    y_max: int = Field(ge=0, le=1000, strict=True)

    @model_validator(mode="after")
    def positive_area(self):
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("Box must have positive area")
        return self


class TargetObservation(Contract):
    target_id: Identifier
    status: Literal["present", "missing", "unsure"]
    observed_quantity: Quantity | None = None
    reason: str | None = None
    label_text: str | None = None
    boxes: list[BoundingBox] = Field(default_factory=list, max_length=32)


class UnexpectedItem(Contract):
    name: str
    item_id: Identifier | None = None
    instead_of_target_id: Identifier | None = None
    quantity: PositiveQuantity | None = None
    boxes: list[BoundingBox] = Field(default_factory=list, max_length=32)


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
    name: str = ""
    verification_mode: VerificationMode = "visible_item"


@dataclass(frozen=True)
class VisionInput:
    capture_id: str
    image: ImageInput
    targets: tuple[VerificationTarget, ...]
    references: tuple[ReferenceImage, ...]
