"""Seed missing demo items in the configured Square Sandbox catalog once."""

import asyncio
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fullfill.adapters.orders.square import SquareOrders, demo_menu
from fullfill.application.order_source import MenuEdit, OrderSourceError


async def seed():
    source = SquareOrders.from_env()
    assert source.catalog is not None
    existing = {item.item_id for item in (await source.menu()).items}
    for item in demo_menu():
        if item.item_id in existing:
            continue
        key = str(
            uuid.uuid5(uuid.NAMESPACE_URL, f"fullfill-menu-v1/{source.location_id}/{item.item_id}")
        )
        await source.catalog.save(
            MenuEdit(
                item_id=item.item_id,
                name=item.name,
                price_cents=item.price_cents,
                version=0,
            ),
            key,
            verification_mode=item.verification_mode,
            require_photo=False,  # Legacy demo fixtures; new kitchen items require real photos.
        )
        print(f"Added {item.name}")
    print(f"Shared menu ready: {len((await source.menu()).items)} items.")


if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    try:
        asyncio.run(seed())
    except OrderSourceError as error:
        raise SystemExit(str(error)) from None
