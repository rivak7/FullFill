"""Browser snapshots, one paid call per reserved attempt, shared Square results."""

import asyncio
import hashlib
import os
from io import BytesIO
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fullfill_contracts.common import Contract, Identifier
from fullfill_contracts.events import OrderState
from fullfill_contracts.vision import ImageInput, ReferenceImage, VisionInput
from PIL import Image
from pydantic import Field, ValidationError

from fullfill.adapters.orders.camera_checks import COOLDOWN_SECONDS, MAX_CHECKS_PER_ORDER
from fullfill.adapters.vision.perceptron import (
    PerceptronVision,
    VisionCallRejected,
    VisionProviderError,
)
from fullfill.application.menu_photo import MenuPhoto
from fullfill.application.order_source import OrderSource, OrderSourceError
from fullfill.domain.compare_order import targets_for

from .order_source import get_order_source

router = APIRouter(prefix="/checks", tags=["checks"])


class CameraCheck(Contract):
    order_id: Identifier
    expected_revision: int = Field(gt=0, strict=True)
    photo: MenuPhoto


def normalized_image(data, edge=1024):
    with Image.open(BytesIO(data)) as image:
        if image.format not in ("JPEG", "PNG") or image.width * image.height > 16_000_000:
            raise ValueError("Unsupported image")
        image.load()
        image = image.convert("RGB")
        image.thumbnail((edge, edge))
        output = BytesIO()
        image.save(output, format="JPEG", quality=80)
        return ImageInput(output.getvalue(), "image/jpeg")


async def reference_image(url):
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    # These URLs come from Square Catalog, never from the browser request.
    if (
        parsed.scheme != "https"
        or parsed.port not in (None, 443)
        or not (
            host.endswith(".squarecdn.com")
            or (
                host.startswith(
                    ("items-images-production.", "square-marketplace.", "square-production.")
                )
                and host.endswith(".amazonaws.com")
            )
        )
    ):
        raise ValueError("Unsupported reference image host")
    async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            data = bytearray()
            async for chunk in response.aiter_bytes():
                data.extend(chunk)
                if len(data) > 2_000_000:
                    raise ValueError("Reference image too large")
    return normalized_image(bytes(data), 640)


@router.get("/camera/config")
async def camera_config(request: Request):
    return {
        "configured": bool(
            os.getenv("PERCEPTRON_API_KEY", "").strip()
            or getattr(request.app.state, "vision_provider", None)
        ),
        "cooldown_seconds": COOLDOWN_SECONDS,
        "max_checks_per_order": MAX_CHECKS_PER_ORDER,
    }


@router.post("/camera", response_model=OrderState)
async def check_camera(
    request: Request,
    source: Annotated[OrderSource, Depends(get_order_source)],
    idempotency_key: Annotated[
        str, Header(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    ],
):
    provider = getattr(request.app.state, "vision_provider", None)
    if provider is None and not os.getenv("PERCEPTRON_API_KEY", "").strip():
        raise HTTPException(503, "Camera checks are not configured on the server.")
    # Bound the body and avoid echoing camera bytes in validation errors.
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2_100_000:
            raise HTTPException(413, "Use a smaller photo (up to 1.5 MB).")
    try:
        body = CameraCheck.model_validate_json(data)
        image = normalized_image(body.photo.data)
    except (ValidationError, ValueError, OSError):
        raise HTTPException(
            422, "Send a valid order, revision, and JPEG or PNG photo up to 1.5 MB."
        ) from None

    order = await source.get_order(body.order_id)
    targets = targets_for(order)
    if not 1 <= len(targets) <= 20:
        raise HTTPException(
            422, "Camera checks support 1–20 different items. Check this order manually."
        )
    reserved, state = await source.reserve_camera_check(
        body.order_id, body.expected_revision, body.photo.digest, idempotency_key
    )
    if reserved is None:
        return state

    try:
        targets = targets_for(state.order)
        menu = await source.menu()
        wanted = {target.item_id for target in targets}
        slots = asyncio.Semaphore(4)

        async def load_reference(item):
            async with slots:
                return ReferenceImage(
                    item_id=item.item_id,
                    revision=item.version,
                    image=await reference_image(item.photo_url),
                )

        async with asyncio.timeout(12):
            references = tuple(
                await asyncio.gather(
                    *[
                        load_reference(item)
                        for item in menu.items
                        if item.item_id in wanted and item.photo_url
                    ]
                )
            )
        vision_input = VisionInput(
            capture_id=hashlib.sha256(idempotency_key.encode()).hexdigest(),
            image=image,
            targets=targets,
            references=references,
        )
        if provider is not None:
            observations = await provider.inspect(vision_input)
        else:
            from perceptron import AsyncClient

            # No retries: a failed or interrupted call may already be billable.
            async with AsyncClient(
                api_key=os.environ["PERCEPTRON_API_KEY"], timeout=30, retries=0
            ) as client:
                observations = await PerceptronVision(
                    client=client, max_output_tokens=min(3000, 200 + 120 * len(targets))
                ).inspect(vision_input)
        return await source.finish_camera_check(reserved, observations)
    except OrderSourceError as error:
        # A revision conflict preserves the worker's newer decision.
        if error.status_code != 409:
            try:
                await source.finish_camera_check(reserved)
            except OrderSourceError:
                pass  # An uncertain/failed save expires visibly, never green.
        raise
    except (
        VisionProviderError,
        VisionCallRejected,
        httpx.HTTPError,
        ValueError,
        OSError,
        KeyError,
        TimeoutError,
        Image.DecompressionBombError,
    ):
        await source.finish_camera_check(reserved)
        raise HTTPException(
            502,
            "The camera check failed. No automatic retry was sent. Check manually or try again.",
        ) from None
