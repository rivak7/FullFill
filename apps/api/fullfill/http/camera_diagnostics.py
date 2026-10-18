"""Per-attempt visual diagnostics returned to the requesting kitchen only."""

import base64

from fullfill_contracts.events import OrderState
from fullfill_contracts.vision import VisionInput
from pydantic import Field


class CameraResponse(OrderState):
    diagnostics: dict | None = Field(default=None, exclude_if=lambda value: value is None)


def input_diagnostics(request: VisionInput, images=True):
    # Bound response size; never shrink or recrop a displayed model input. Without
    # images this is a few kilobytes, so every check returns it.
    remaining = 3_000_000 if images else 0

    def image_url(image):
        nonlocal remaining
        size = 4 * ((len(image.data) + 2) // 3)
        if size > remaining:
            return None
        remaining -= size
        return f"data:{image.media_type};base64,{base64.b64encode(image.data).decode()}"

    wanted = {target.item_id for target in request.targets}
    return {
        "provider_called": False,
        "image": image_url(request.image),
        "targets": [target.model_dump(mode="json") for target in request.targets],
        "references": [
            {
                "item_id": ref.item_id,
                "name": ref.name,
                "revision": ref.revision,
                "role": "expected" if ref.item_id in wanted else "alternative",
                "image": image_url(ref.image),
            }
            for ref in request.references
        ],
        "observations": None,
    }
