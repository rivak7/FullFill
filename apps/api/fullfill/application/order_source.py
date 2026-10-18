"""Order ingress boundary. Screens consume FullFill orders, not provider responses."""

from typing import Protocol

from fullfill_contracts.common import Contract
from fullfill_contracts.orders import OrderSnapshot, VerificationMode
from pydantic import Field, model_validator


class MenuEntry(Contract):
    item_id: str
    name: str
    description: str
    price_cents: int = Field(ge=0)
    currency: str = "USD"
    verification_mode: VerificationMode = "visible_item"


class RequestedItem(Contract):
    item_id: str = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=50, strict=True)


class CreateOrder(Contract):
    items: list[RequestedItem] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_items(self):
        if len({item.item_id for item in self.items}) != len(self.items):
            raise ValueError("Use one quantity per menu item.")
        return self


class OrderSourceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class OrderSource(Protocol):
    async def list_orders(self) -> list[OrderSnapshot]: ...

    async def get_order(self, order_id: str) -> OrderSnapshot: ...

    async def create_order(self, request: CreateOrder, idempotency_key: str) -> OrderSnapshot: ...
