"""Validated menu photos, kept below the hosted API's request-size limit."""

import base64
import binascii
import hashlib
from io import BytesIO

from fullfill_contracts.common import Contract
from PIL import Image, UnidentifiedImageError
from pydantic import Field, PrivateAttr, model_validator


class MenuPhoto(Contract):
    data_base64: str = Field(min_length=1, max_length=2_000_000, repr=False)
    _data: bytes = PrivateAttr(default=b"")
    _content_type: str = PrivateAttr(default="")

    @model_validator(mode="after")
    def validate_image(self):
        try:
            data = base64.b64decode(self.data_base64, validate=True)
            if not data or len(data) > 1_500_000:
                raise ValueError
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG") or image.width * image.height > 16_000_000:
                    raise ValueError
                content_type = Image.MIME[image.format]
                image.verify()
            # verify() checks the container; load() also rejects truncated pixel data.
            with Image.open(BytesIO(data)) as image:
                image.load()
        except (
            ValueError,
            binascii.Error,
            OSError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
        ):
            raise ValueError(
                "Use a valid JPEG or PNG photo up to 1.5 MB and 16 megapixels."
            ) from None
        self._data = data
        self._content_type = content_type
        return self

    @property
    def data(self) -> bytes:
        return self._data

    @property
    def content_type(self) -> str:
        return self._content_type

    @property
    def digest(self) -> str:
        return hashlib.sha256(self._data).hexdigest()
