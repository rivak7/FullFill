"""Order ingress boundary. Screens consume FullFill orders, not provider responses."""

from typing import Literal, Protocol

from fullfill_contracts.common import Contract
from fullfill_contracts.events import OrderState
from fullfill_contracts.orders import OrderSnapshot, VerificationMode
from pydantic import Field, model_validator

from .menu_photo import MenuPhoto


class MenuEntry(Contract):
    item_id: str
    name: str
    description: str
    price_cents: int = Field(ge=0)
    currency: str = "USD"
    verification_mode: VerificationMode = "visible_item"
    available: bool = True
    archived: bool = False
    version: int = 0
    photo_id: str | None = None
    photo_url: str | None = None


class MenuSnapshot(Contract):
    revision: str
    items: list[MenuEntry]


class MenuEdit(Contract):
    item_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    price_cents: int = Field(ge=0, le=1000000, strict=True)
    available: bool = True
    archived: bool = False
    version: int = Field(ge=0, strict=True)
    photo: MenuPhoto | None = None

    @model_validator(mode="after")
    def clean_name(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Enter an item name.")
        return self


class RequestedItem(Contract):
    item_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=50, strict=True)


class CreateOrder(Contract):
    items: list[RequestedItem] = Field(min_length=1, max_length=20)
    menu_revision: str | None = Field(default=None, max_length=64)
    quote: str | None = Field(default=None, max_length=40000)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("Use one quantity per menu item.")
        return self


class OrderSourceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class OrderStatusEdit(Contract):
    status: Literal["unfulfilled", "unsure", "fulfilled"]
    expected_revision: int = Field(gt=0, strict=True)
    worker_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class OrderClaimEdit(Contract):
    worker_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    expected_revision: int = Field(gt=0, strict=True)
    release: bool = False


class OrderSource(Protocol):
    async def reserve_camera_check(
        self, order_id: str, revision: int, image_digest: str, request_key: str, worker_id: str
    ) -> tuple[dict | None, OrderState]: ...

    async def finish_camera_check(
        self, reserved: dict, observations=None, reference_version=None, confirmed=False
    ) -> OrderState: ...

    async def confirm_camera_check(
        self, order_id: str, check_id: str, revision: int, worker_id: str, scene_unchanged: bool
    ) -> OrderState: ...

    async def claim_order(self, order_id: str, edit: OrderClaimEdit) -> OrderState: ...

    async def menu(self) -> MenuSnapshot: ...

    async def save_menu(self, edit: MenuEdit, idempotency_key: str) -> MenuSnapshot: ...

    async def prepare_order(self, request: CreateOrder, idempotency_key: str) -> CreateOrder: ...

    async def list_orders(self) -> list[OrderSnapshot]: ...

    async def station_orders(
        self, *, cleanup: bool = False, clear: bool = False
    ) -> list[OrderState]: ...

    async def set_order_status(
        self, order_id: str, edit: OrderStatusEdit, idempotency_key: str
    ) -> OrderState: ...

    async def get_order(self, order_id: str) -> OrderSnapshot: ...

    async def create_order(self, request: CreateOrder, idempotency_key: str) -> OrderSnapshot: ...
