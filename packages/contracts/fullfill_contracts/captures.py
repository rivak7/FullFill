"""Capture wire metadata; image bytes travel separately as multipart data."""

from typing import Literal

from pydantic import AwareDatetime, Field

from .common import Contract, Identifier, Revision


class CaptureMetadata(Contract):
    schema_version: Literal[1] = 1
    station_id: Identifier
    session_id: Identifier
    scene_sequence: int = Field(ge=0, strict=True)
    captured_at: AwareDatetime
    camera_profile_id: Identifier
    purpose: Literal["check", "reference"]
    qr_candidate: str | None = None
    request_id: str | None = None


class OrderContext(Contract):
    order_id: Identifier
    order_revision: Revision
    disposition_revision: Revision


class CaptureReceipt(Contract):
    capture_id: Identifier
    order_context: OrderContext | None = None


class CaptureRequest(Contract):
    request_id: Identifier
    station_id: Identifier
    purpose: Literal["check", "reference"]
    order_context: OrderContext | None = None


class CreateCaptureRequest(Contract):
    purpose: Literal["check", "reference"]
    order_context: OrderContext | None = None
