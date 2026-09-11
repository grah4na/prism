"""Response-direction tests (no docker needed)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from prism.hosts import Host  # noqa: E402
from prism.models import Resp  # noqa: E402
from prism.scoring import Verdict, judge_response  # noqa: E402
from prism.table import build_response_groups, build_response_matrix  # noqa: E402


def _host(name="t", **kw):
    base = dict(
        name=name, container=None, addr="127.0.0.1", port=80, tls=False, wait=0.05
    )
    base.update(kw)
    return Host(**base)


def _resp(code=b"200", reason=b"OK", headers=None, body=b""):
    return Resp(b"1.1", code, reason, headers or [], body)


def test_comparable_headers_drop_volatile():
    r = _resp(
        headers=[
            (b"Date", b"x"),
            (b"Server", b"nginx"),
            (b"Content-Length", b"3"),
            (b"Transfer-Encoding", b"chunked"),
            (b"Connection", b"close"),
            (b"Keep-Alive", b"timeout=5"),
            (b"ETag", b'"abc"'),
            (b"Last-Modified", b"y"),
            (b"Via", b"1.1 proxy"),
            (b"X-Cache", b"HIT"),
            (b"X-Foo", b"Bar"),
        ]
    )
    assert r.comparable_headers() == [(b"x-foo", b"Bar")]


def test_comparable_headers_lowercase_and_sorted():
    r = _resp(headers=[(b"X-B", b"2"), (b"x-a", b"1")])
    assert r.comparable_headers() == [(b"x-a", b"1"), (b"x-b", b"2")]


def test_comparable_body_blanked_for_200():
    assert _resp(code=b"200", body=b'{"trace"}').comparable_body() == b""
    assert _resp(code=b"400", body=b"nope").comparable_body() == b"nope"


def test_judge_response_agrees_across_volatile_and_traces():
    a = _resp(code=b"200", headers=[(b"Server", b"a"), (b"Date", b"1")], body=b"one")
    b = _resp(code=b"200", headers=[(b"Server", b"b"), (b"Date", b"2")], body=b"two")
    assert judge_response([a], [b], _host("a"), _host("b")) == Verdict.OK


def test_judge_response_agrees_on_reason_case():
    a = _resp(code=b"400", reason=b"Bad Request", body=b"x")
    b = _resp(code=b"400", reason=b"Bad request", body=b"x")
    assert judge_response([a], [b], _host("a"), _host("b")) == Verdict.OK


def test_judge_response_disagrees_on_code():
    a = _resp(code=b"200")
    b = _resp(code=b"400", reason=b"Bad Request")
    assert (
        judge_response([a], [b], _host("a"), _host("b")) == Verdict.RESPONSE_DISCREPANCY
    )


def test_judge_response_disagrees_on_header():
    a = _resp(code=b"400", reason=b"Bad Request", headers=[(b"X-A", b"1")], body=b"x")
    b = _resp(code=b"400", reason=b"Bad Request", headers=[(b"X-A", b"2")], body=b"x")
    assert (
        judge_response([a], [b], _host("a"), _host("b")) == Verdict.RESPONSE_DISCREPANCY
    )


def test_judge_response_disagrees_on_reason():
    a = _resp(code=b"400", reason=b"Bad Request")
    b = _resp(code=b"400", reason=b"Nope")
    assert (
        judge_response([a], [b], _host("a"), _host("b")) == Verdict.RESPONSE_DISCREPANCY
    )


def test_judge_response_disagrees_on_rejection_body():
    a = _resp(code=b"400", reason=b"Bad Request", body=b"one")
    b = _resp(code=b"400", reason=b"Bad Request", body=b"two")
    assert (
        judge_response([a], [b], _host("a"), _host("b")) == Verdict.RESPONSE_DISCREPANCY
    )


def test_judge_response_stream_length_mismatch():
    a = _resp(code=b"400", reason=b"Bad Request")
    assert judge_response([a], [], _host("a"), _host("b")) == Verdict.STREAM_DISCREPANCY
    assert judge_response([], [a], _host("a"), _host("b")) == Verdict.STREAM_DISCREPANCY


def test_judge_response_no_keepalive_truncates():
    a = [_resp(code=b"200"), _resp(code=b"400", reason=b"Bad Request")]
    b = [_resp(code=b"200")]
    assert judge_response(a, b, _host("a", no_keepalive=True), _host("b")) == Verdict.OK


def test_build_response_matrix_shape_and_values():
    hosts = [_host("a"), _host("b")]
    rows = [
        [_resp(code=b"200")],
        [_resp(code=b"400", reason=b"Bad Request")],
    ]
    m = build_response_matrix(rows, hosts)
    assert m[0][0] == Verdict.OK
    assert m[1][0] is None
    assert m[0][1] == Verdict.RESPONSE_DISCREPANCY
    assert m[1][1] == Verdict.OK


def test_build_response_groups():
    hosts = [_host("a"), _host("b"), _host("c")]
    rows = [
        [_resp(code=b"200", headers=[(b"X", b"same")])],
        [_resp(code=b"200", headers=[(b"x", b"same")])],
        [_resp(code=b"400", reason=b"Bad Request")],
    ]
    groups = build_response_groups(rows, hosts)
    assert [tuple(h.name for h in g) for g in groups] == [("a", "b"), ("c",)]
