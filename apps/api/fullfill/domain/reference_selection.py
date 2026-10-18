"""Cheap reference selection; no model calls and no guarantee of visual identity."""

import hashlib
import json
import re
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps

MAX_ALTERNATIVES = 6


def reference_fingerprint(menu):
    # Catalog versions conservatively invalidate evidence, including same-URL photo edits.
    values = sorted(
        (
            item.item_id,
            item.name,
            item.photo_id,
            item.photo_url,
            item.verification_mode,
            item.archived,
            item.version,
        )
        for item in menu.items
    )
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=128)
def visual_features(data):
    with Image.open(BytesIO(data)) as image:
        image = ImageOps.fit(image.convert("RGB"), (32, 32))
        # Spatial color and grayscale contrast help retrieve similar containers.
        colors = tuple(value / 255 for pixel in image.resize((8, 8)).getdata() for value in pixel)
        gray = list(image.convert("L").resize((8, 8)).getdata())
        mean = sum(gray) / len(gray)
        shape = tuple((value - mean) / 255 for value in gray)
        return colors, shape


def choose_alternatives(menu, wanted, images):
    ordered = [item for item in menu.items if item.item_id in wanted]
    candidates = [
        item
        for item in menu.items
        if item.item_id not in wanted and not item.archived and item.item_id in images
    ]
    if len(candidates) <= MAX_ALTERNATIVES:
        return sorted(candidates, key=lambda item: item.item_id)

    def distance(first, second):
        color_a, shape_a = visual_features(images[first.item_id].data)
        color_b, shape_b = visual_features(images[second.item_id].data)
        color = sum(abs(a - b) for a, b in zip(color_a, color_b, strict=True)) / len(color_a)
        shape = sum(abs(a - b) for a, b in zip(shape_a, shape_b, strict=True)) / len(shape_a)
        tokens_a = set(re.findall(r"\w+", first.name.casefold()))
        tokens_b = set(re.findall(r"\w+", second.name.casefold()))
        names = len(tokens_a & tokens_b) / max(1, len(tokens_a | tokens_b))
        return color * 0.5 + shape * 0.5 - names * 0.15

    # Round-robin each expected item so a single family doesn't take every slot.
    ranked = [
        sorted(candidates, key=lambda other: (distance(item, other), other.item_id))
        for item in sorted(ordered, key=lambda item: item.item_id)
    ]
    chosen = {}
    for position in range(len(candidates)):
        for choices in ranked:
            item = choices[position]
            chosen[item.item_id] = item
            if len(chosen) == MAX_ALTERNATIVES:
                return list(chosen.values())
    return list(chosen.values())
