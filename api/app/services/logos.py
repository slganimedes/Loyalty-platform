"""Validate PNG uploads before storing their bytes in SQLite."""

import base64
import binascii
import struct
import zlib

MAX_LOGO_BYTES = 2 * 1024 * 1024


def decode_logo(value: str) -> bytes:
    try:
        data = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Logo must be base64-encoded PNG") from exc
    if len(data) > MAX_LOGO_BYTES:
        raise ValueError("Logo must be at most 2 MB")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Logo must be a PNG image")
    offset = 8
    has_header = has_pixels = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 8 + length
        if end + 4 > len(data):
            break
        payload = data[offset + 8 : end]
        checksum = int.from_bytes(data[end : end + 4], "big")
        if zlib.crc32(kind + payload) != checksum:
            raise ValueError("Invalid PNG checksum")
        if not has_header:
            if kind != b"IHDR" or length != 13:
                raise ValueError("Invalid PNG header")
            width, height = struct.unpack(">II", payload[:8])
            if not (1 <= width <= 2048 and 1 <= height <= 2048):
                raise ValueError("Logo dimensions must be between 1 and 2048 pixels")
            has_header = True
        if kind == b"IDAT" and length:
            has_pixels = True
        if kind == b"IEND":
            if length == 0 and has_pixels and end + 4 == len(data):
                return data
            break
        offset = end + 4
    raise ValueError("Incomplete PNG image")
