from __future__ import annotations

import dataclasses
import itertools


class H2Err(Exception):
    pass


# Frame type numbers (RFC 7540 s6).
DATA = 0
HEADERS = 1
PRIORITY = 2
RST = 3
SETTINGS = 4
PUSH = 5
PING = 6
GOAWAY = 7
WIN = 8
CONT = 9

_NAMES = {
    0: "DATA",
    1: "HEADERS",
    2: "PRIORITY",
    3: "RST_STREAM",
    4: "SETTINGS",
    5: "PUSH_PROMISE",
    6: "PING",
    7: "GOAWAY",
    8: "WINDOW_UPDATE",
    9: "CONTINUATION",
}


class FType(int):
    def __repr__(self) -> str:  # keep "H2FrameType.X" style-ish output simple
        return f"H2FrameType.{_NAMES.get(int(self), hex(int(self)))}"


FType.DATA = FType(0)
FType.HEADERS = FType(1)
FType.PRIORITY = FType(2)
FType.RST_STREAM = FType(3)
FType.SETTINGS = FType(4)
FType.PUSH_PROMISE = FType(5)
FType.PING = FType(6)
FType.GOAWAY = FType(7)
FType.WINDOW_UPDATE = FType(8)
FType.CONTINUATION = FType(9)


@dataclasses.dataclass
class FFlags:
    unused7: bool = False
    unused6: bool = False
    priority: bool = False
    unused4: bool = False
    padded: bool = False
    end_headers: bool = False
    unused1: bool = False
    end_stream: bool = False  # == ack for SETTINGS/PING

    @classmethod
    def decode(cls, v: bytes | int) -> "FFlags":
        if isinstance(v, bytes):
            if len(v) != 1:
                raise H2Err("flag byte")
            v = v[0]
        if not 0 <= v < 256:
            raise H2Err("flag range")
        bits = [(v >> i) & 1 == 1 for i in reversed(range(8))]
        return cls(*bits)

    def encode(self) -> bytes:
        vals = (
            self.unused7,
            self.unused6,
            self.priority,
            self.unused4,
            self.padded,
            self.end_headers,
            self.unused1,
            self.end_stream,
        )
        return bytes([sum(b << (7 - i) for i, b in enumerate(vals))])

    def __repr__(self) -> str:
        on = ",".join(f"{k}={v}" for k, v in self.__dict__.items() if v)
        return f"H2Flags({on})"

    def __bool__(self) -> bool:
        return any(self.__dict__.values())


@dataclasses.dataclass
class Frame:
    typ: FType
    flags: FFlags = dataclasses.field(default_factory=FFlags)
    reserved: bool = False
    sid: int = 0
    payload: bytes = b""

    def __post_init__(self) -> None:
        if not 0 <= self.sid < (1 << 31):
            raise H2Err("stream id")
        if len(self.payload) >= (1 << 24):
            raise H2Err("payload too big")

    @classmethod
    def scan(cls, src) -> "Frame":
        src = iter(src)
        try:
            first = next(src)
        except StopIteration:
            raise StopIteration
        head = bytes(itertools.chain([first], itertools.islice(src, 8)))
        if len(head) < 9:
            raise H2Err("short header")
        ln = int.from_bytes(head[0:3], "big")
        typ = FType(head[3])
        flg = FFlags.decode(head[4])
        raw = int.from_bytes(head[5:9], "big")
        body = bytes(itertools.islice(src, ln))
        if len(body) != ln:
            raise H2Err(f"short body {body!r}")
        return cls(typ, flg, bool(raw >> 31), raw & ~(1 << 31), body)

    def wire(self) -> bytes:
        return (
            len(self.payload).to_bytes(3, "big")
            + int(self.typ).to_bytes(1, "big")
            + self.flags.encode()
            + ((self.reserved << 31) | self.sid).to_bytes(4, "big")
            + self.payload
        )


def scan_all(blob: bytes | bytearray | memoryview) -> list[Frame]:
    out: list[Frame] = []
    it = iter(bytes(blob))
    while True:
        try:
            out.append(Frame.scan(it))
        except StopIteration:
            break
    return out
