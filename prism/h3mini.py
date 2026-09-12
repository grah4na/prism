from __future__ import annotations

import dataclasses

from .models import Resp


class H3Err(Exception):
    pass


# Frame types.
DATA = 0x0
HEADERS = 0x1
CANCEL_PUSH = 0x2
SETTINGS = 0x3
PUSH_PROMISE = 0x4
GOAWAY = 0x5
MAX_PUSH_ID = 0x6

_NAMES = {
    DATA: "DATA",
    HEADERS: "HEADERS",
    CANCEL_PUSH: "CANCEL_PUSH",
    SETTINGS: "SETTINGS",
    PUSH_PROMISE: "PUSH_PROMISE",
    GOAWAY: "GOAWAY",
    MAX_PUSH_ID: "MAX_PUSH_ID",
}


class FType(int):
    def __repr__(self) -> str:
        return f"H3FrameType.{_NAMES.get(int(self), hex(int(self)))}"


for _n, _v in list(_NAMES.items()):
    setattr(FType, _v, FType(_n))


def encode_varint(n: int) -> bytes:
    """QUIC variable-length integer (RFC 9000 s16)."""
    if n < 0:
        raise H3Err("negative varint")
    if n < 2**6:
        return bytes([n])
    if n < 2**14:
        return (0x4000 | n).to_bytes(2, "big")
    if n < 2**30:
        return (0x80000000 | n).to_bytes(4, "big")
    if n < 2**62:
        return (0xC000000000000000 | n).to_bytes(8, "big")
    raise H3Err("varint too big")


def decode_varint(blob: bytes, offset: int = 0) -> tuple[int, int]:
    """Return (value, next_offset) for a varint starting at offset."""
    if offset >= len(blob):
        raise H3Err("short varint")
    first = blob[offset]
    prefix = first >> 6
    if prefix == 0:
        return first & 0x3F, offset + 1
    size = 1 << prefix
    if offset + size > len(blob):
        raise H3Err("short varint")
    mask = (1 << (size * 8 - 2)) - 1
    return int.from_bytes(blob[offset : offset + size], "big") & mask, offset + size


@dataclasses.dataclass
class Frame:
    typ: FType
    payload: bytes = b""

    def __post_init__(self) -> None:
        if len(self.payload) >= 2**62:
            raise H3Err("payload too big")

    def wire(self) -> bytes:
        return (
            encode_varint(int(self.typ))
            + encode_varint(len(self.payload))
            + self.payload
        )


def scan_one(blob: bytes) -> tuple[Frame, bytes]:
    typ, off = decode_varint(blob, 0)
    length, off = decode_varint(blob, off)
    end = off + length
    if end > len(blob):
        raise H3Err("short frame body")
    return Frame(FType(typ), blob[off:end]), blob[end:]


def scan_all(blob: bytes) -> list[Frame]:
    out: list[Frame] = []
    rest = blob
    while rest:
        frame, rest = scan_one(rest)
        out.append(frame)
    return out


@dataclasses.dataclass
class H3Reply:
    """A decoded HTTP/3 response: :status, non-pseudo fields, body."""

    status: bytes
    headers: list[tuple[bytes, bytes]]
    body: bytes

    @classmethod
    def from_fields(cls, fields: list[tuple[bytes, bytes]], body: bytes) -> "H3Reply":
        status = b""
        headers: list[tuple[bytes, bytes]] = []
        for k, v in fields:
            if k == b":status":
                status = v
            elif not k.startswith(b":"):
                headers.append((k, v))
        return cls(status, headers, body)

    def to_resp(self) -> Resp:
        return Resp(b"3", self.status, b"", self.headers, self.body)
