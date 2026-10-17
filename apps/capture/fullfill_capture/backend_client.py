"""Camera-to-backend interface only. Implement HTTP without importing API internals."""

from typing import Protocol

from fullfill_contracts.captures import CaptureMetadata, CaptureReceipt, CaptureRequest
from fullfill_contracts.checks import CheckAccepted, CreateCheckRequest
from fullfill_contracts.vision import ImageInput


class CaptureBackend(Protocol):
    async def pending_requests(self, station_id: str) -> list[CaptureRequest]: ...

    async def upload(
        self, metadata: CaptureMetadata, image: ImageInput, idempotency_key: str
    ) -> CaptureReceipt: ...

    async def start_check(
        self, request: CreateCheckRequest, idempotency_key: str
    ) -> CheckAccepted: ...
