"""WebSocket envelope and station snapshot. There is no event server yet."""

from typing import Literal

from pydantic import Field

from .checks import CheckResult, Disposition
from .common import Contract, Identifier, Revision
from .orders import OrderSnapshot


class OrderState(Contract):
    order: OrderSnapshot
    disposition: Disposition
    disposition_revision: Revision
    current_check: CheckResult | None = None


class StationSnapshot(Contract):
    schema_version: Literal[1] = 1
    station_id: Identifier
    event_cursor: str | None = None
    orders: list[OrderState] = Field(default_factory=list)


class StationEvent(Contract):
    schema_version: Literal[1] = 1
    event_id: Identifier
    station_id: Identifier
    event_type: Literal[
        "check.queued",
        "check.completed",
        "check.failed",
        "order.updated",
        "resync_required",
    ]
    order_state: OrderState | None = None
