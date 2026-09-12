"""Permissive HTTP/1 parsing, written from scratch for compatible output."""

from __future__ import annotations

import base64
import binascii
import copy
import gzip
import json
import re
from collections.abc import Sequence

from .models import Req, Resp

_RESP_LINE = re.compile(
    rb"\A(?P<ver>[^\s]+)[\v\f\r \t]+(?P<code>\d+)[\v\f\r \t]+(?P<reason>.*?)\r?\n"
)
_REQ_LINE = re.compile(
    rb"\A(?P<method>[^\s]+)\s+(?P<uri>[^\s]+)\s+(?:HTTP/(?P<ver>[^\s]+))?\r?\n"
)
_HDR_LINE = re.compile(rb"\A(?P<name>[^:\n]+):[ \t]*(?P<val>.*?)[ \t]*\Z")
_HDR_END = re.compile(rb"\r?\n\r?\n")
_CHUNK_HDR = re.compile(rb"\A(?P<hex>[0-9a-fA-F]+)[^\n]*\r?\n")


def _short_version(raw: bytes) -> bytes:
    if raw.startswith(b"HTTP/"):
        return raw[len(b"HTTP/") :]
    return raw


def split_headers(blob: bytes) -> tuple[list[tuple[bytes, bytes]], bytes]:
    """Cut header block off the front of blob."""
    if blob.startswith(b"\r\n"):
        return [], blob[2:]
    m = _HDR_END.search(blob)
    if m is None:
        raise ValueError("headers not terminated")
    block = blob[: m.start()]
    rest = blob[m.end() :]
    found: list[tuple[bytes, bytes]] = []
    # re.split on \r?\n keeps empty pieces out; skip empties defensively.
    for line in re.split(rb"\r?\n", block):
        if line == b"":
            continue
        hm = _HDR_LINE.match(line)
        if hm is None:
            raise ValueError(f"bad header line: {line!r}")
        found.append((hm.group("name"), hm.group("val")))
    return found, rest


def carve_body(
    hdrs: Sequence[tuple[bytes, bytes]], tail: bytes, *, reply: bool
) -> tuple[bytes, bytes]:
    """Return (body, leftover) following Prism rules."""
    length: int | None = None
    te_vals: list[bytes] = []
    ce_vals: list[bytes] = []
    for k, v in hdrs:
        kl = k.lower()
        if kl == b"content-length":
            if not v.isascii() or not v.isdigit():
                raise ValueError("bad Content-Length")
            length = int(v)
        elif kl == b"transfer-encoding":
            te_vals.append(v.lower().strip(b","))
        elif kl == b"content-encoding":
            ce_vals.append(v.lower().strip(b","))

    if reply and length is None and b"chunked" not in te_vals:
        return tail, b""

    if b"chunked" in te_vals:
        if b"gzip" in ce_vals:
            raise ValueError("gzip+chunked unsupported")
        out = b""
        cursor = tail
        while True:
            hm = _CHUNK_HDR.match(cursor)
            if hm is None:
                raise ValueError("bad chunk header")
            cursor = cursor[hm.end() :]
            size = int(hm.group("hex"), 16)
            # match exactly size bytes + CRLF
            pat = rf"\A(?P<d>[\x00-\xff]{{{size}}})\r\n".encode("latin1")
            dm = re.match(pat, cursor)
            if dm is None:
                raise ValueError("bad chunk data")
            out += dm.group("d")
            cursor = cursor[dm.end() :]
            if size == 0:
                break
        return out, cursor

    if length is not None:
        chunk = tail[:length]
        rest = tail[length:]
        if b"gzip" in ce_vals:
            chunk = gzip.decompress(chunk)
        return chunk, rest
    return b"", tail


def read_response(blob: bytes) -> tuple[Resp, bytes]:
    m = _RESP_LINE.match(blob)
    if m is None:
        raise ValueError("bad status line")
    hdrs, tail = split_headers(blob[m.end() :])
    body, leftover = carve_body(hdrs, tail, reply=True)
    return (
        Resp(
            version=_short_version(m.group("ver")),
            code=m.group("code"),
            reason=m.group("reason"),
            headers=hdrs,
            body=body,
        ),
        leftover,
    )


def read_request(blob: bytes) -> tuple[Req, bytes]:
    m = _REQ_LINE.match(blob)
    if m is None:
        raise ValueError("bad request line")
    hdrs, tail = split_headers(blob[m.end() :])
    body, leftover = carve_body(hdrs, tail, reply=False)
    ver = m.group("ver")
    if ver is None:
        ver = b"0.9"
    return (
        Req(
            method=m.group("method"),
            uri=m.group("uri"),
            version=ver,
            headers=hdrs,
            body=body,
        ),
        leftover,
    )


def read_request_stream(blob: bytes) -> tuple[list[Req], bytes]:
    acc: list[Req] = []
    rest = blob
    while rest != b"":
        try:
            one, rest = read_request(rest)
        except ValueError:
            break
        acc.append(one)
    return acc, rest


# -- helpers that mirror Prism utils, renamed --


def drop_header(req: Req, name: bytes) -> Req:
    dup = copy.deepcopy(req)
    want = name.lower()
    dup.headers = [(k, v) for k, v in req.headers if k.lower() != want]
    return dup


def merge_dup_headers(req: Req, glue: bytes) -> Req:
    dup = copy.deepcopy(req)
    merged: dict[bytes, bytes] = {}
    for k, v in dup.headers:
        lk = k.lower()
        if lk in merged:
            merged[lk] = merged[lk] + glue + v
        else:
            merged[lk] = v
    dup.headers = list(merged.items())
    return dup


def remap_header_names(req: Req, table: dict[bytes, bytes]) -> Req:
    dup = copy.deepcopy(req)
    out: list[tuple[bytes, bytes]] = []
    for k, v in dup.headers:
        nk = k
        for old, new in table.items():
            nk = nk.replace(old, new)
        out.append((nk, v))
    dup.headers = out
    return dup


def decode_trace(body: bytes) -> Req:
    """Decode the JSON trace the echo servers return (base64 fields)."""
    try:
        doc = json.loads(
            body,
            parse_float=lambda s: s,
            parse_int=lambda s: s,
            parse_constant=lambda s: s,
        )
    except json.JSONDecodeError as e:
        raise ValueError(f"trace not JSON: {body!r}") from e
    try:
        assert isinstance(doc, dict)
        for need in ("headers", "uri", "body", "method", "version"):
            assert need in doc
        assert isinstance(doc["headers"], list)
        assert isinstance(doc["uri"], str)
        assert isinstance(doc["body"], str)
        assert isinstance(doc["method"], str)
        assert isinstance(doc["version"], str)
        hdrs: list[tuple[bytes, bytes]] = []
        for pair in doc["headers"]:
            assert isinstance(pair, list) and len(pair) == 2
            assert isinstance(pair[0], str) and isinstance(pair[1], str)
            hdrs.append((base64.b64decode(pair[0]).lower(), base64.b64decode(pair[1])))
        ver = base64.b64decode(doc["version"])
        ver = _short_version(ver)
        return Req(
            method=base64.b64decode(doc["method"]),
            uri=base64.b64decode(doc["uri"]),
            version=ver,
            headers=hdrs,
            body=base64.b64decode(doc["body"]),
        )
    except (binascii.Error, AssertionError) as e:
        raise ValueError("bad trace shape") from e


def trim_09(blob: bytes) -> bytes:
    at = blob.find(b"\r\n\r\n")
    if at == -1:
        return blob
    return blob[at + 4 :]


def read_09_reply(blob: bytes) -> Resp:
    if not blob.startswith(b"<"):
        raise ValueError("not an 0.9 body")
    m = re.search(rb"(\d\d\d)", blob)
    if m is None:
        raise ValueError("no code in 0.9 body")
    return Resp(b"0.9", m.group(1), b"", [], b"")
