"""Boundary for optional messaging; no Photon-specific fields."""

from typing import Literal

from .common import Contract, Identifier


class Notification(Contract):
    notification_id: Identifier
    deduplication_key: Identifier
    kind: Literal["error", "override", "shift_summary"]
    message: str


class DeliveryResult(Contract):
    status: Literal["sent", "failed"]
    provider_receipt: str | None = None
    error_code: str | None = None
