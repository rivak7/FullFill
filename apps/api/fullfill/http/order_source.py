"""Dependency used by the order queue and the station snapshot."""

from fastapi import Request

from fullfill.adapters.orders.square import SquareOrders
from fullfill.application.order_source import OrderSource


def get_order_source(request: Request) -> OrderSource:
    source = request.app.state.order_source
    return source if source is not None else SquareOrders.from_env()
