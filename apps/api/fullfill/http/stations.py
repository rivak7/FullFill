"""Polling snapshot for the Square queue; vision results are connected separately."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fullfill_contracts.events import OrderState, StationSnapshot

from fullfill.application.order_source import OrderSource

from .order_source import get_order_source

router = APIRouter(prefix="/stations", tags=["stations"])


@router.post("/{station_id}/refresh", response_model=StationSnapshot)
async def refresh_station(
    station_id: str, source: Annotated[OrderSource, Depends(get_order_source)]
):
    orders = await source.refresh_orders()
    return StationSnapshot(
        station_id=station_id,
        orders=[
            OrderState(order=order, disposition="pending", disposition_revision=order.revision)
            for order in orders
        ],
    )


@router.get("/{station_id}", response_model=StationSnapshot)
async def get_station(station_id: str, source: Annotated[OrderSource, Depends(get_order_source)]):
    orders = await source.list_orders()
    return StationSnapshot(
        station_id=station_id,
        orders=[
            OrderState(order=order, disposition="pending", disposition_revision=order.revision)
            for order in orders
        ],
    )
