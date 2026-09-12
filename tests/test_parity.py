import io
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
# Original code builds yml paths from sys.path[0], so force it to tools dir
# before importing anything from tools/.
sys.path.insert(0, TOOLS)
sys.path.insert(0, ROOT)
sys.path[0] = TOOLS

# Originals
import diff as orig_diff
import grid as orig_grid
import http1 as orig_http
from targets import Server as OrigServer

# Ours
from prism import table as my_table
from prism.hosts import Host
from prism.http_parse import Req, Resp, read_request, read_response
from prism.models import Req as MyReq, Resp as MyResp
from prism.pretty import show_matrix, show_req, show_resp
from prism.scoring import Verdict, judge

import repl as orig_repl


def _orig_host(**kw):
    base = dict(
        name="t",
        container=None,
        address="127.0.0.1",
        port=80,
        requires_tls=False,
        timeout=0.05,
        allows_http_0_9=False,
        allows_http_2=False,
        added_headers=[],
        requires_length_in_post=False,
        allows_missing_host_header=False,
        header_name_translation={},
        doesnt_support_version=False,
        method_character_blacklist=b"",
        method_whitelist=None,
        removed_headers=[],
        trashed_headers=[],
        doesnt_support_persistence=False,
        requires_specific_host_header=False,
        joins_duplicate_headers=False,
        duplicate_header_joiner=b"",
    )
    base.update(kw)
    return OrigServer(**base)


def _my_host(**kw):
    base = dict(
        name="t",
        container=None,
        addr="127.0.0.1",
        port=80,
        tls=False,
        wait=0.05,
    )
    base.update(kw)
    return Host(**base)


def test_parse_request_parity():
    blob = b"GET / HTTP/1.1\r\nHost: a\r\nX: b\r\n\r\nhello"
    o_req, o_rest = orig_http.parse_request(blob)
    m_req, m_rest = read_request(blob)
    assert (m_req.method, m_req.uri, m_req.version, m_req.headers, m_req.body) == (
        o_req.method,
        o_req.uri,
        o_req.version,
        o_req.headers,
        o_req.body,
    )
    assert m_rest == o_rest


def test_parse_response_parity():
    blob = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
    o_resp, o_rest = orig_http.parse_response(blob)
    m_resp, m_rest = read_response(blob)
    assert (m_resp.version, m_resp.code, m_resp.reason) == (
        o_resp.version,
        o_resp.code,
        o_resp.reason,
    )
    assert m_rest == o_rest


def test_chunked_parity():
    blob = b"POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nWiki\r\n0\r\n\r\nREST"
    o_req, o_rest = orig_http.parse_request(blob)
    m_req, m_rest = read_request(blob)
    assert m_req.body == o_req.body == b"Wiki"
    assert m_rest == o_rest


def test_judge_parity():
    ha_o = _orig_host(name="a")
    hb_o = _orig_host(name="b")
    ha_m = _my_host(name="a")
    hb_m = _my_host(name="b")
    a_o = [orig_http.HTTPRequest(b"GET", b"/", [(b"host", b"a")], b"", b"1.1")]
    b_o = [orig_http.HTTPRequest(b"GET", b"/", [(b"host", b"a")], b"", b"1.1")]
    a_m = [MyReq(b"GET", b"/", b"1.1", [(b"host", b"a")], b"")]
    b_m = [MyReq(b"GET", b"/", b"1.1", [(b"host", b"a")], b"")]
    assert (
        orig_diff.categorize_discrepancy(a_o, b_o, ha_o, hb_o).name
        == judge(a_m, b_m, ha_m, hb_m).name
    )
    # mismatch case
    b_o2 = [orig_http.HTTPResponse(b"1.1", b"400", b"Bad", [], b"")]
    b_m2 = [MyResp(b"1.1", b"400", b"Bad", [], b"")]
    assert (
        orig_diff.categorize_discrepancy(a_o, b_o2, ha_o, hb_o).name
        == judge(a_m, b_m2, ha_m, hb_m).name
    )


def test_print_parity():
    r = MyReq(b"GET", b"/", b"1.1", [(b"host", b"a")], b"")
    o = orig_http.HTTPRequest(b"GET", b"/", [(b"host", b"a")], b"", b"1.1")
    buf1, buf2 = io.StringIO(), io.StringIO()
    with redirect_stdout(buf1):
        show_req(r)
    with redirect_stdout(buf2):
        orig_repl.print_request(o)
    assert buf1.getvalue() == buf2.getvalue()

    rr = MyResp(b"1.1", b"400", b"Bad Request", [], b"")
    oo = orig_http.HTTPResponse(b"1.1", b"400", b"Bad Request", [], b"")
    buf1, buf2 = io.StringIO(), io.StringIO()
    with redirect_stdout(buf1):
        show_resp(rr)
    with redirect_stdout(buf2):
        orig_repl.print_response(oo)
    assert buf1.getvalue() == buf2.getvalue()


def test_grid_parity():
    ha_o = _orig_host(name="gunicorn")
    hb_o = _orig_host(name="hyper")
    ha_m = _my_host(name="gunicorn")
    hb_m = _my_host(name="hyper")
    pts_o = [
        [orig_http.HTTPRequest(b"GET", b"/", [(b"host", b"a")], b"", b"1.1")],
        [orig_http.HTTPRequest(b"GET", b"/", [(b"host", b"a")], b"", b"1.1")],
    ]
    pts_m = [
        [MyReq(b"GET", b"/", b"1.1", [(b"host", b"a")], b"")],
        [MyReq(b"GET", b"/", b"1.1", [(b"host", b"a")], b"")],
    ]
    g_o = orig_grid.generate_grid(pts_o, [ha_o, hb_o])
    g_m = my_table.build_matrix(pts_m, [ha_m, hb_m])
    assert [c.name if c else None for row in g_o for c in row] == [
        c.name if c else None for row in g_m for c in row
    ]

    buf1, buf2 = io.StringIO(), io.StringIO()
    with redirect_stdout(buf1):
        show_matrix(g_m, ["gunicorn", "hyper"])
    with redirect_stdout(buf2):
        orig_repl.print_grid(g_o, ["gunicorn", "hyper"])
    assert buf1.getvalue() == buf2.getvalue()
