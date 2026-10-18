"""Create demo orders and read the shared POS queue."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fullfill_contracts.events import OrderState
from fullfill_contracts.orders import OrderSnapshot

from fullfill.application.order_source import (
    CreateOrder,
    OrderClaimEdit,
    OrderSource,
    OrderStatusEdit,
)

from .order_source import get_order_source

router = APIRouter(prefix="/orders", tags=["orders"])
Source = Annotated[OrderSource, Depends(get_order_source)]


@router.get("", response_model=list[OrderSnapshot])
async def list_orders(source: Source):
    return await source.list_orders()


@router.post("", response_model=OrderSnapshot, status_code=201)
async def create_order(
    body: CreateOrder,
    source: Source,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=192, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await source.create_order(body, idempotency_key)


@router.post("/prepare", response_model=CreateOrder)
async def prepare_order(
    body: CreateOrder,
    source: Source,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=192, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await source.prepare_order(body, idempotency_key)


@router.get("/{order_id}", response_model=OrderSnapshot)
async def get_order(order_id: str, source: Source):
    return await source.get_order(order_id)


@router.post("/{order_id}/status", response_model=OrderState)
async def set_order_status(
    order_id: str,
    body: OrderStatusEdit,
    source: Source,
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=192, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    return await source.set_order_status(order_id, body, idempotency_key)


@router.post("/{order_id}/claim", response_model=OrderState)
async def claim_order(order_id: str, body: OrderClaimEdit, source: Source):
    return await source.claim_order(order_id, body)
