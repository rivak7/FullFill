"""Stable reasons shared by model parsing, Square storage, and the display."""

REASONS = {
    "visibility": "hidden, blurry, or outside the camera view",
    "identity": "cannot distinguish this item or its hidden contents",
    "label": "unlabeled or the readable label does not identify this item",
    "count": "cannot count the items reliably",
    "unknown": "not clearly visible or distinguishable",
}
REASON_CODES = dict(zip(REASONS, "vilcu", strict=True))

SCENES = {
    "clear": None,
    "obscured": "Uncover the items and keep hands out of the camera view.",
    "blurry": "Hold the items still and check the camera focus and lighting.",
    "out_of_frame": "Keep the entire order inside the camera preview.",
    "mixed_orders": "Keep only the selected order in the camera preview.",
}
