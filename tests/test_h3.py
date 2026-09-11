"""HTTP/3 frame + QPACK unit tests (no docker needed)."""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from prism import h3mini  # noqa: E402
from prism.h3mini import H3Err  # noqa: E402
from prism import qpack  # noqa: E402


@pytest.mark.parametrize(
    "value",
    [0, 1, 63, 64, 16383, 16384, 2**30 - 1, 2**30, 2**62 - 1],
)
def test_varint_round_trip(value):
    assert h3mini.decode_varint(h3mini.encode_varint(value)) == (
        value,
        len(h3mini.encode_varint(value)),
    )


def test_varint_known_vectors():
    assert h3mini.encode_varint(0) == b"\x00"
    assert h3mini.encode_varint(63) == b"\x3f"
    assert h3mini.encode_varint(64) == b"\x40\x40"
    assert h3mini.encode_varint(16383) == b"\x7f\xff"


def test_varint_negative_rejected():
    with pytest.raises(H3Err):
        h3mini.encode_varint(-1)


def test_frame_round_trip():
    frame = h3mini.Frame(h3mini.FType.DATA, b"hello")
    scanned, rest = h3mini.scan_one(frame.wire())
    assert rest == b""
    assert scanned.typ == h3mini.FType.DATA
    assert scanned.payload == b"hello"


def test_scan_all_multiple_frames():
    blob = b"".join(
        h3mini.Frame(t, p).wire()
        for t, p in [(h3mini.DATA, b"a"), (h3mini.HEADERS, b"\x00\x00")]
    )
    frames = h3mini.scan_all(blob)
    assert [int(f.typ) for f in frames] == [h3mini.DATA, h3mini.HEADERS]
    assert [f.payload for f in frames] == [b"a", b"\x00\x00"]


def test_h3reply_splits_status_and_drops_pseudo():
    reply = h3mini.H3Reply.from_fields(
        [(b":status", b"200"), (b":method", b"GET"), (b"content-type", b"text/plain")],
        b"body",
    )
    assert reply.status == b"200"
    assert reply.headers == [(b"content-type", b"text/plain")]
    assert reply.body == b"body"
    resp = reply.to_resp()
    assert (resp.code, resp.reason, resp.body) == (b"200", b"", b"body")


@pytest.mark.parametrize("prefix_bits", [3, 4, 6, 7, 8])
def test_qpack_int_round_trip(prefix_bits):
    for value in [
        0,
        1,
        (1 << (prefix_bits - 1)) - 1,
        (1 << (prefix_bits - 1)),
        200,
        100000,
    ]:
        blob = qpack.encode_int(value, prefix_bits)
        got, off = qpack.decode_int(blob, 0, prefix_bits)
        assert got == value
        assert off == len(blob)


def test_qpack_string_round_trip():
    for prefix_bits in (4, 8):
        for data in (b"", b"a", b"x" * 200):
            blob = qpack.encode_string(data, prefix_bits)
            got, off = qpack.decode_string(blob, 0, prefix_bits)
            assert got == data
            assert off == len(blob)


def test_qpack_static_table_length():
    assert len(qpack.STATIC_TABLE) == 99


def test_qpack_field_section_round_trip():
    fields = [
        (b":status", b"200"),
        (b"content-type", b"application/json"),
        (b"server", b"mine"),
        (b"x-custom", b"yes"),
    ]
    blob = qpack.encode_field_section(fields)
    assert qpack.decode_field_section(blob) == fields


def test_qpack_indexed_static_vector():
    # :path=/ is static index 1; encode as indexed static field line.
    assert qpack.decode_field_section(b"\x00\x00\xc1") == [(b":path", b"/")]


def test_qpack_dynamic_reference_rejected():
    # Indexed Field Line with T=0 (dynamic) is not supported.
    with pytest.raises(H3Err):
        qpack.decode_field_section(b"\x00\x00\x80")


def test_qpack_huffman_rejected():
    # Literal with literal name, H bit set on the name string (0x20 | 0x08).
    with pytest.raises(H3Err):
        qpack.decode_field_section(b"\x00\x00\x28")
