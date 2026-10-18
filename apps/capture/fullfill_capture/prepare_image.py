"""Turn a settled camera frame into the JPEG sent for a check.

TODO: local QR reading and ticket masking.
"""

from fullfill_contracts.vision import ImageInput

from .trigger import crop_mat


def prepare_upload(frame, mat_roi=None, max_side: int = 1024, jpeg_quality: int = 85) -> ImageInput:
    """Crop to the mat, shrink the longest side to `max_side`, and encode as JPEG."""
    import cv2

    mat = crop_mat(frame, mat_roi)
    scale = max_side / max(mat.shape[:2])
    if scale < 1:
        size = (round(mat.shape[1] * scale), round(mat.shape[0] * scale))
        mat = cv2.resize(mat, size, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", mat, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
    if not ok:
        raise ValueError("could not encode frame as JPEG")
    return ImageInput(data=encoded.tobytes(), media_type="image/jpeg")
