from io import BytesIO

from fullfill.application.order_source import MenuEntry, MenuSnapshot
from fullfill.domain.reference_selection import (
    MAX_REFERENCES,
    choose_alternatives,
    reference_fingerprint,
)
from fullfill_contracts.vision import ImageInput
from PIL import Image


def item(identity, name=None, **changes):
    return MenuEntry(
        item_id=identity, name=name or identity, description="", price_cents=100, **changes
    )


def image(color):
    data = BytesIO()
    Image.new("RGB", (32, 32), color).save(data, format="JPEG")
    return ImageInput(data.getvalue(), "image/jpeg")


def test_small_menu_includes_sold_out_alternatives_but_not_archived_or_unpictured():
    menu = MenuSnapshot(
        revision="1",
        items=[
            item("wanted"),
            item("sold", available=False),
            item("archived", archived=True),
            item("no-photo"),
        ],
    )
    images = {name: image("white") for name in ["wanted", "sold", "archived"]}
    assert [entry.item_id for entry in choose_alternatives(menu, {"wanted"}, images)] == ["sold"]


def test_larger_menu_uses_visual_neighbors_and_covers_each_ordered_item():
    colors = {
        "white": "white",
        "black": "black",
        "near-white": "#fefefe",
        "near-black": "#010101",
        **{f"red-{i}": f"#{150 + i:02x}0000" for i in range(8)},
    }
    menu = MenuSnapshot(revision="1", items=[item(name) for name in colors])
    images = {name: image(color) for name, color in colors.items()}
    selected = [entry.item_id for entry in choose_alternatives(menu, {"white", "black"}, images)]
    assert len(selected) == len(set(selected)) == 6
    assert selected[:2] == ["near-black", "near-white"]
    assert not {"white", "black"} & set(selected)


def test_similar_names_win_over_similar_photos():
    names = {
        "tsss": "TSSS",
        "tssss": "TSSSS",
        "chicken": "Chicken burrito",
        "steak": "Steak burrito",
        **{f"packet-{i}": f"Packet {i}" for i in range(8)},
    }
    menu = MenuSnapshot(revision="1", items=[item(key, name) for key, name in names.items()])
    # Every photo looks the same: one white mat.
    images = {key: image("white") for key in names}
    selected = [entry.item_id for entry in choose_alternatives(menu, {"tsss", "chicken"}, images)]
    assert selected[:2] == ["steak", "tssss"]


def test_total_references_stay_under_the_cap():
    names = [f"item-{i:02d}" for i in range(30)]
    menu = MenuSnapshot(revision="1", items=[item(name) for name in names])
    images = {name: image("white") for name in names}
    for ordered in (1, 6, 9, 12, 15):
        wanted = set(names[:ordered])
        alternatives = choose_alternatives(menu, wanted, images)
        assert len(alternatives) == min(6, max(0, MAX_REFERENCES - ordered))
        assert not wanted & {entry.item_id for entry in alternatives}


def test_reference_fingerprint_ignores_order_but_detects_replacements_and_modes():
    menu = MenuSnapshot(revision="1", items=[item("a"), item("b")])
    original = reference_fingerprint(menu)
    menu.items.reverse()
    assert reference_fingerprint(menu) == original
    for field, value in [
        ("photo_id", "new"),
        ("photo_url", "https://new"),
        ("version", 2),
        ("verification_mode", "label"),
        ("name", "Renamed"),
        ("archived", True),
    ]:
        changed = menu.model_copy(deep=True)
        setattr(changed.items[0], field, value)
        assert reference_fingerprint(changed) != original


def test_reference_download_cache_is_versioned(monkeypatch):
    import asyncio

    import httpx
    from fullfill.http import checks

    checks._reference_cache.clear()
    requests = []
    original = httpx.AsyncClient

    def response(request):
        requests.append(request)
        return httpx.Response(200, content=image("white").data)

    monkeypatch.setattr(
        checks.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(response), **kwargs),
    )

    async def download():
        url = "https://items-images-production.s3.amazonaws.com/cache-test.jpg"
        await checks.reference_image(url, 1)
        await checks.reference_image(url, 1)
        assert len(requests) == 1
        await checks.reference_image(url, 2)
        assert len(requests) == 2

    asyncio.run(download())
    checks._reference_cache.clear()
