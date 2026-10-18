"""Create demo orders and read the shared POS queue."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fullfill_contracts.orders import OrderSnapshot

from fullfill.application.order_source import CreateOrder, OrderSource

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


@router.get("/{order_id}", response_model=OrderSnapshot)
async def get_order(order_id: str, source: Source):
    return await source.get_order(order_id)
