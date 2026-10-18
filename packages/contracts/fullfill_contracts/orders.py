"""Order and catalog data shared by the backend, UI, capture, and evaluation."""

from typing import Literal

from pydantic import Field

from .common import Contract, Identifier, PositiveQuantity, Revision

VerificationMode = Literal["visible_item", "label", "container_count"]


class OrderLine(Contract):
    line_id: Identifier
    item_id: Identifier
    name: str
    quantity: PositiveQuantity
    verification_mode: VerificationMode = "visible_item"
    requires_manual_review: bool = False


class OrderSnapshot(Contract):
    schema_version: Literal[1] = 1
    order_id: Identifier
    revision: Revision
    lines: list[OrderLine] = Field(min_length=1)
    # What people call the order: "001", "002"... Restarts after the queue is cleared.
    display_number: str | None = Field(default=None, pattern=r"^\d{3}$")


class MenuItem(Contract):
    item_id: Identifier
    name: str
    verification_mode: VerificationMode = "visible_item"
    label_aliases: list[str] = Field(default_factory=list)


class ReferenceSet(Contract):
    item_id: Identifier
    revision: Revision
    camera_profile_id: Identifier
    image_asset_ids: list[Identifier] = Field(min_length=1)
