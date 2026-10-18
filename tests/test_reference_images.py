"""Reference downloads use fake HTTP, without vision calls."""

import asyncio
from io import BytesIO

import httpx
import pytest
from fullfill.http.checks import _reference_cache, reference_image
from PIL import Image


def test_square_sandbox_photo_can_be_loaded(monkeypatch):
    output = BytesIO()
    Image.new("RGB", (64, 64), "yellow").save(output, format="JPEG")
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(200, content=output.getvalue())

    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(serve), **kwargs),
    )
    _reference_cache.clear()
    result = asyncio.run(
        reference_image("https://items-images-sandbox.s3.us-west-2.amazonaws.com/files/test.jpeg")
    )
    assert result.media_type == "image/jpeg"
    assert len(requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://items-images-sandbox.s3.us-west-2.amazonaws.com.attacker.example/test.jpeg",
        "https://unrelated-bucket.s3.us-west-2.amazonaws.com/test.jpeg",
        "http://items-images-sandbox.s3.us-west-2.amazonaws.com/test.jpeg",
    ],
)
def test_untrusted_reference_hosts_still_rejected(url):
    with pytest.raises(ValueError, match="Unsupported reference image host"):
        asyncio.run(reference_image(url))
