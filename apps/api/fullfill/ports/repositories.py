"""Storage contracts only; implementations and transaction boundaries are team work."""

from typing import Protocol

from fullfill_contracts.checks import CheckResult
from fullfill_contracts.orders import MenuItem, OrderSnapshot, ReferenceSet


class OrderRepository(Protocol):
    async def get(self, order_id: str) -> OrderSnapshot | None: ...

    async def list(self) -> list[OrderSnapshot]: ...

    async def save(self, order: OrderSnapshot) -> None: ...


class CatalogRepository(Protocol):
    async def list_items(self) -> list[MenuItem]: ...

    async def get_references(self, item_id: str) -> ReferenceSet | None: ...


class CheckRepository(Protocol):
    async def get(self, check_id: str) -> CheckResult | None: ...

    async def save(self, result: CheckResult) -> None: ...


class AssetStore(Protocol):
    async def get(self, asset_id: str) -> bytes: ...

    async def put(self, content: bytes, media_type: str, purpose: str) -> str: ...
