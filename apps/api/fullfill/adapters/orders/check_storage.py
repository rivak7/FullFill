"""Lossless result storage within Square's per-object metadata limits."""

import base64
import json
import zlib

RESULT_KEYS = ("fullfill_camera_result_0", "fullfill_camera_result_1")
PREFIX = "fullfill_result_"


def pack_result(payload, metadata, lines):
    packed = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if len(packed) > 510:
        packed = "z:" + base64.b64encode(zlib.compress(packed.encode())).decode()
    split = min(255, len(packed) - 1)
    chunks = [packed[:split], packed[split : split + 255]]
    chunks.extend(packed[index : index + 255] for index in range(split + 255, len(packed), 255))
    metadata.update(zip(RESULT_KEYS, chunks[:2], strict=True))
    patches = []
    index = 2
    for line in lines:
        values = dict(line.get("metadata") or {})
        owned = [key for key in values if key.startswith(PREFIX)]
        # Remove old overflow in this same version-checked write. A nonempty
        # space is valid Square metadata and ignored by the decoder.
        for key in owned:
            del values[key]
        if not line.get("uid"):
            continue
        while index < len(chunks) and len(values) < 10:
            values[f"{PREFIX}{index}"] = chunks[index]
            index += 1
        for key in owned:
            if key not in values:
                values[key] = " "
        # Reusing old keys can otherwise exceed the limit after a redistribution.
        if len(values) > 10:
            raise ValueError("Check result metadata has too many keys")
        if values != (line.get("metadata") or {}):
            patches.append({"uid": line["uid"], "metadata": values})
    if index < len(chunks):
        raise ValueError("The full check result cannot be saved; review manually")
    return len(chunks), patches


def unpack_result(metadata, lines, count=2):
    chunks = {index: metadata.get(key, "") for index, key in enumerate(RESULT_KEYS)}
    for line in lines:
        for key, value in (line.get("metadata") or {}).items():
            if key.startswith(PREFIX) and value.strip():
                index = int(key[len(PREFIX) :])
                if index in chunks:
                    raise ValueError("Duplicate result chunk")
                chunks[index] = value
    packed = "".join(chunks[index] for index in range(count))
    if packed.startswith("z:"):
        decoder = zlib.decompressobj()
        packed = decoder.decompress(base64.b64decode(packed[2:]), 100_000)
        if not decoder.eof or decoder.unconsumed_tail:
            raise ValueError("Invalid compressed result")
    return json.loads(packed)
