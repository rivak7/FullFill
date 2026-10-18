"""Cheap reference selection; no model calls and no guarantee of visual identity."""

import hashlib
import json
from difflib import SequenceMatcher
from functools import lru_cache
from io import BytesIO

from PIL import Image, ImageOps

# Ordered items always get their photo; lookalikes fill the rest, up to a total that
# keeps a check well inside Perceptron's context.
MAX_REFERENCES = 12
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


def name_similarity(first, second):
    # TSSS and TSSSS share no whole word, but their names are 89% alike.
    return SequenceMatcher(None, first.casefold(), second.casefold()).ratio()


def choose_alternatives(menu, wanted, images):
    ordered = [item for item in menu.items if item.item_id in wanted]
    limit = min(MAX_ALTERNATIVES, max(0, MAX_REFERENCES - len(ordered)))
    candidates = [
        item
        for item in menu.items
        if item.item_id not in wanted and not item.archived and item.item_id in images
    ]
    if len(candidates) <= limit:
        return sorted(candidates, key=lambda item: item.item_id)

    def distance(first, second):
        # Similar names are the strongest hint of a lookalike (TSSS vs TSSSS, Chicken vs
        # Steak burrito). The photos only break ties: on one mat they mostly show the mat.
        color_a, shape_a = visual_features(images[first.item_id].data)
        color_b, shape_b = visual_features(images[second.item_id].data)
        color = sum(abs(a - b) for a, b in zip(color_a, color_b, strict=True)) / len(color_a)
        shape = sum(abs(a - b) for a, b in zip(shape_a, shape_b, strict=True)) / len(shape_a)
        names = name_similarity(first.name, second.name)
        return (1 - names) * 0.7 + (color * 0.5 + shape * 0.5) * 0.3

    # Round-robin each expected item so a single family doesn't take every slot.
    ranked = [
        sorted(candidates, key=lambda other: (distance(item, other), other.item_id))
        for item in sorted(ordered, key=lambda item: item.item_id)
    ]
    chosen = {}
    for position in range(len(candidates)):
        for choices in ranked:
            if len(chosen) == limit:
                return list(chosen.values())
            item = choices[position]
            chosen[item.item_id] = item
    return list(chosen.values())
