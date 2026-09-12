from __future__ import annotations

from .h3mini import H3Err

# RFC 9204 Appendix A, indexed from 0.
STATIC_TABLE: list[tuple[bytes, bytes]] = [
    (b":authority", b""),
    (b":path", b"/"),
    (b"age", b"0"),
    (b"content-disposition", b""),
    (b"content-length", b"0"),
    (b"cookie", b""),
    (b"date", b""),
    (b"etag", b""),
    (b"if-modified-since", b""),
    (b"if-none-match", b""),
    (b"last-modified", b""),
    (b"link", b""),
    (b"location", b""),
    (b"referer", b""),
    (b"set-cookie", b""),
    (b":method", b"CONNECT"),
    (b":method", b"DELETE"),
    (b":method", b"GET"),
    (b":method", b"HEAD"),
    (b":method", b"OPTIONS"),
    (b":method", b"POST"),
    (b":method", b"PUT"),
    (b":scheme", b"http"),
    (b":scheme", b"https"),
    (b":status", b"103"),
    (b":status", b"200"),
    (b":status", b"304"),
    (b":status", b"404"),
    (b":status", b"503"),
    (b"accept", b"*/*"),
    (b"accept", b"application/dns-message"),
    (b"accept-encoding", b"gzip, deflate, br"),
    (b"accept-ranges", b"bytes"),
    (b"access-control-allow-headers", b"cache-control"),
    (b"access-control-allow-headers", b"content-type"),
    (b"access-control-allow-origin", b"*"),
    (b"cache-control", b"max-age=0"),
    (b"cache-control", b"max-age=2592000"),
    (b"cache-control", b"max-age=604800"),
    (b"cache-control", b"no-cache"),
    (b"cache-control", b"no-store"),
    (b"cache-control", b"public, max-age=31536000"),
    (b"content-encoding", b"br"),
    (b"content-encoding", b"gzip"),
    (b"content-type", b"application/dns-message"),
    (b"content-type", b"application/javascript"),
    (b"content-type", b"application/json"),
    (b"content-type", b"application/x-www-form-urlencoded"),
    (b"content-type", b"image/gif"),
    (b"content-type", b"image/jpeg"),
    (b"content-type", b"image/png"),
    (b"content-type", b"text/css"),
    (b"content-type", b"text/html; charset=utf-8"),
    (b"content-type", b"text/plain"),
    (b"content-type", b"text/plain;charset=utf-8"),
    (b"range", b"bytes=0-"),
    (b"strict-transport-security", b"max-age=31536000"),
    (b"strict-transport-security", b"max-age=31536000; includesubdomains"),
    (b"strict-transport-security", b"max-age=31536000; includesubdomains; preload"),
    (b"vary", b"accept-encoding"),
    (b"vary", b"origin"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-xss-protection", b"1; mode=block"),
    (b":status", b"100"),
    (b":status", b"204"),
    (b":status", b"206"),
    (b":status", b"302"),
    (b":status", b"400"),
    (b":status", b"403"),
    (b":status", b"421"),
    (b":status", b"425"),
    (b":status", b"500"),
    (b"accept-language", b""),
    (b"access-control-allow-credentials", b"FALSE"),
    (b"access-control-allow-credentials", b"TRUE"),
    (b"access-control-allow-headers", b"*"),
    (b"access-control-allow-methods", b"get"),
    (b"access-control-allow-methods", b"get, post, options"),
    (b"access-control-allow-methods", b"options"),
    (b"access-control-expose-headers", b"content-length"),
    (b"access-control-request-headers", b"content-type"),
    (b"access-control-request-method", b"get"),
    (b"access-control-request-method", b"post"),
    (b"alt-svc", b"clear"),
    (b"authorization", b""),
    (
        b"content-security-policy",
        b"script-src 'none'; object-src 'none'; base-uri 'none'",
    ),
    (b"early-data", b"1"),
    (b"expect-ct", b""),
    (b"forwarded", b""),
    (b"if-range", b""),
    (b"origin", b""),
    (b"purpose", b"prefetch"),
    (b"server", b""),
    (b"timing-allow-origin", b"*"),
    (b"upgrade-insecure-requests", b"1"),
    (b"user-agent", b""),
    (b"x-forwarded-for", b""),
    (b"x-frame-options", b"deny"),
    (b"x-frame-options", b"sameorigin"),
]


def encode_int(value: int, prefix_bits: int) -> bytes:
    """Prefixed integer (RFC 7541 s5.1, reused by QPACK)."""
    max_prefix = (1 << prefix_bits) - 1
    if value < max_prefix:
        return bytes([value])
    out = bytearray([max_prefix])
    value -= max_prefix
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def decode_int(blob: bytes, offset: int, prefix_bits: int) -> tuple[int, int]:
    """Return (value, next_offset)."""
    if offset >= len(blob):
        raise H3Err("short integer")
    max_prefix = (1 << prefix_bits) - 1
    value = blob[offset] & max_prefix
    offset += 1
    if value < max_prefix:
        return value, offset
    shift = 0
    while True:
        if offset >= len(blob):
            raise H3Err("short integer")
        byte = blob[offset]
        offset += 1
        value += (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, offset
        shift += 7


def encode_string(data: bytes, prefix_bits: int) -> bytes:
    """String literal without Huffman coding (H bit is zero)."""
    return encode_int(len(data), prefix_bits - 1) + data


def decode_string(blob: bytes, offset: int, prefix_bits: int) -> tuple[bytes, int]:
    """Return (data, next_offset); Huffman is rejected for now."""
    if offset >= len(blob):
        raise H3Err("short string")
    huffman = bool(blob[offset] & (1 << (prefix_bits - 1)))
    length, offset = decode_int(blob, offset, prefix_bits - 1)
    end = offset + length
    if end > len(blob):
        raise H3Err("short string")
    data = blob[offset:end]
    if huffman:
        raise H3Err("Huffman strings unsupported")
    return data, end


def _static(idx: int) -> tuple[bytes, bytes]:
    if not 0 <= idx < len(STATIC_TABLE):
        raise H3Err(f"invalid static table index {idx}")
    return STATIC_TABLE[idx]


def _find_static_entry(name: bytes, value: bytes) -> int | None:
    for i, (n, v) in enumerate(STATIC_TABLE):
        if n == name and v == value:
            return i
    return None


def _find_static_name(name: bytes) -> int | None:
    for i, (n, _) in enumerate(STATIC_TABLE):
        if n == name:
            return i
    return None


def _flagged(encoded: bytes, flags: int) -> bytes:
    out = bytearray(encoded)
    out[0] |= flags
    return bytes(out)


def encode_field_section(fields: list[tuple[bytes, bytes]]) -> bytes:
    """Encode a field section using only the static table (RIC=Base=0)."""
    out = bytearray(b"\x00\x00")
    for name, value in fields:
        idx = _find_static_entry(name, value)
        if idx is not None:
            out += _flagged(encode_int(idx, 6), 0xC0)
            continue
        name_idx = _find_static_name(name)
        if name_idx is not None:
            out += _flagged(encode_int(name_idx, 4), 0x40 | 0x10)
            out += encode_string(value, 8)
            continue
        out += _flagged(encode_string(name, 4), 0x20)
        out += encode_string(value, 8)
    return bytes(out)


def decode_field_section(blob: bytes) -> list[tuple[bytes, bytes]]:
    """Decode a field section; dynamic-table references are rejected."""
    if not blob:
        raise H3Err("empty field section")
    ric, off = decode_int(blob, 0, 8)  # Required Insert Count
    if off >= len(blob):
        raise H3Err("short field section prefix")
    s_bit = bool(blob[off] & 0x80)
    delta, off = decode_int(blob, off, 7)
    base = ric + delta if not s_bit else ric - delta - 1
    if base < 0:
        raise H3Err("negative base")
    _ = (ric, base)  # static-only decoder; dynamic refs are rejected below
    fields: list[tuple[bytes, bytes]] = []
    while off < len(blob):
        first = blob[off]
        if first & 0x80:  # Indexed Field Line
            static = bool(first & 0x40)
            idx, off = decode_int(blob, off, 6)
            if not static:
                raise H3Err("dynamic table reference unsupported")
            fields.append(_static(idx))
        elif first & 0x40:  # Literal Field Line with Name Reference
            static = bool(first & 0x10)
            idx, off = decode_int(blob, off, 4)
            if not static:
                raise H3Err("dynamic table reference unsupported")
            name = _static(idx)[0]
            value, off = decode_string(blob, off, 8)
            fields.append((name, value))
        elif first & 0x20:  # Literal Field Line with Literal Name
            name, off = decode_string(blob, off, 4)
            value, off = decode_string(blob, off, 8)
            fields.append((name, value))
        elif first & 0x10:  # Indexed Field Line with Post-Base Index
            raise H3Err("post-base index unsupported")
        else:  # Literal Field Line with Post-Base Name Reference
            raise H3Err("post-base index unsupported")
    return fields
