"""Core message shapes for Prism.

These mirror what the Prism prints (HTTPRequest / HTTPResponse) so output
stays identical, but internals/names are our own.
"""

from __future__ import annotations

import dataclasses

# Headers that are ignored when comparing two requests. The Prism ignores
# framing headers because every server normalizes them differently.
_IGNORED_COMPARE = frozenset(
    [
        b"content-length",
        b"content_length",
        b"transfer-encoding",
        b"transfer_encoding",
    ]
)

# Bytes allowed in tokens (method names, header names). Same set as RFC tchars.
_ALLOWED_TOKEN = frozenset(
    b"!#$%&'*+-.^_`|~"
    b"abcdefghijklmnopqrstuvwxyz"
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    b"0123456789"
)
_FORBIDDEN_VALUE = frozenset(b"\r\n\x00")


@dataclasses.dataclass
class Req:
    """A parsed HTTP request seen by the echo backend."""

    method: bytes
    uri: bytes
    version: bytes
    headers: list[tuple[bytes, bytes]]
    body: bytes

    def has(self, name: bytes, value: bytes | None = None) -> bool:
        want = name.lower()
        for k, v in self.headers:
            if k.lower() == want and (value is None or v == value):
                return True
        return False

    def comparable_headers(self) -> list[tuple[bytes, bytes]]:
        out = [
            (k.lower(), v) for k, v in self.headers if k.lower() not in _IGNORED_COMPARE
        ]
        out.sort()
        return out

    def looks_valid(self) -> bool:
        for k, _ in self.headers:
            if any(c not in _ALLOWED_TOKEN for c in k):
                return False
        for _, v in self.headers:
            if any(c in _FORBIDDEN_VALUE for c in v):
                return False
        if any(c not in _ALLOWED_TOKEN for c in self.method):
            return False
        return True

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Req):
            return False
        if self.method != other.method:
            return False
        if self.uri != other.uri:
            return False
        if self.body != other.body:
            return False
        if self.comparable_headers() != other.comparable_headers():
            return False
        # Empty version means "don't care" (used by some backends).
        if (
            self.version != other.version
            and self.version != b""
            and other.version != b""
        ):
            return False
        return True


@dataclasses.dataclass
class Resp:
    """A parsed HTTP response (rejection) from a server."""

    version: bytes
    code: bytes
    reason: bytes
    headers: list[tuple[bytes, bytes]]
    body: bytes

    def __eq__(self, other: object) -> bool:
        # The Prism only compares status codes for responses.
        if not isinstance(other, Resp):
            return False
        return self.code == other.code


Msg = Req | Resp
