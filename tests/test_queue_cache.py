"""Warm queue reads query changes, without dropping old unresolved tickets."""

import asyncio
import copy
import json

import httpx
import pytest
from fullfill.adapters.orders.square import SquareOrders
from fullfill.application.order_source import OrderSourceError
from test_square_orders import square_order


def test_queue_reads_beyond_old_twenty_page_limit_without_retaining_archived_history():
    pages = []

    def request(request):
        body = json.loads(request.content)
        page = int(body.get("cursor", "0"))
        pages.append(page)
        assert body["limit"] == 1000
        return httpx.Response(
            200,
            json={
                "orders": [
                    square_order(f"archived-{page}", metadata={"fullfill_queue_archived": "true"})
                ]
                if page < 22
                else [square_order("old-unresolved")],
                **({"cursor": str(page + 1)} if page < 22 else {}),
            },
        )

    source = SquareOrders(
        "token", "test-location", transport=httpx.MockTransport(request), queue_cache=True
    )

    async def scenario():
        assert [order.order_id for order in await source.list_orders()] == ["old-unresolved"]
        assert len(source._queue_orders) == 1
        await source.list_orders()
        assert len(pages) == 23

    asyncio.run(scenario())


def test_incremental_queue_preserves_old_work_updates_removals_and_retries_failed_pages(
    monkeypatch,
):
    now = [1000.0]
    monkeypatch.setattr("fullfill.adapters.orders.queue_cache.time.time", lambda: now[0])
    pages = []
    response = {
        "orders": [
            square_order("old", created_at="2020-01-01"),
            square_order("new", created_at="2025-01-01"),
        ]
    }
    fail_page = [False]

    def request(request):
        body = json.loads(request.content)
        pages.append(body)
        if fail_page[0] and body.get("cursor"):
            return httpx.Response(503, json={})
        return httpx.Response(200, json=copy.deepcopy(response))

    source = SquareOrders(
        "token", "test-location", transport=httpx.MockTransport(request), queue_cache=True
    )

    async def scenario():
        assert len(await source.list_orders()) == 2
        response["orders"] = [square_order("new", state="CANCELED", version=4)]
        now[0] += 1
        assert [order.order_id for order in await source.list_orders()] == ["old"]
        query = pages[-1]["query"]
        assert query["sort"]["sort_field"] == "UPDATED_AT"
        assert "state_filter" not in query["filter"]
        assert "start_at" in query["filter"]["date_time_filter"]["updated_at"]
        synced = source._queue_synced
        # A partial page must not publish a deletion or advance the cursor.
        response.update(orders=[square_order("old", state="CANCELED", version=4)], cursor="next")
        fail_page[0] = True
        now[0] += 1
        with pytest.raises(OrderSourceError):
            await source.list_orders()
        assert source._queue_synced == synced
        assert "old" in source._queue_orders
        del response["cursor"]
        fail_page[0] = False
        assert await source.list_orders() == []

    asyncio.run(scenario())


def test_local_write_survives_search_lag_and_periodic_rebuild_removes_deleted_work(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("fullfill.adapters.orders.queue_cache.time.time", lambda: now[0])
    old = square_order("old", created_at="2020-01-01")
    records = [old]

    def request(_request):
        return httpx.Response(200, json={"orders": records})

    source = SquareOrders(
        "token", "test-location", transport=httpx.MockTransport(request), queue_cache=True
    )

    async def scenario():
        await source.list_orders()
        newer = {**old, "version": 4}
        source._remember_order(newer, local=True)
        now[0] += 1
        assert (await source.list_orders())[0].revision == 4
        now[0] += 601
        records.clear()
        assert await source.list_orders() == []

    asyncio.run(scenario())


def test_concurrent_refreshes_share_one_search():
    calls = []

    async def request(_request):
        calls.append(True)
        await asyncio.sleep(0)
        return httpx.Response(200, json={"orders": [square_order()]})

    source = SquareOrders(
        "token", "test-location", transport=httpx.MockTransport(request), queue_cache=True
    )

    async def scenario():
        results = await asyncio.gather(*(source.list_orders() for _ in range(5)))
        assert all(len(result) == 1 for result in results)
        assert len(calls) == 1

    asyncio.run(scenario())
