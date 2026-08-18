"""Discrepancy scoring (own implementation, same decisions as Prism)."""

from __future__ import annotations

import enum
import itertools

from .hosts import Host
from .http_parse import drop_header, merge_dup_headers, remap_header_names
from .models import Msg, Req, Resp
from .nethelp import swap_bytes


class Verdict(enum.Enum):
    OK = 0
    TYPE_DISCREPANCY = 1
    RESPONSE_DISCREPANCY = 2
    REQUEST_DISCREPANCY = 3
    STREAM_DISCREPANCY = 4
    INVALID = 5
    DISCREPANCY = 6


def scrub(one: Req, me: Host, other: Host) -> Req:
    """Normalize `one` (seen by me) so it can be compared with other's view."""
    cur = one
    if other.join_dup:
        cur = merge_dup_headers(cur, other.join_glue)
    for k in me.extra_headers:
        cur = drop_header(cur, k)
    for k in (swap_bytes(k, me.rename) for k in other.extra_headers):
        cur = drop_header(cur, k)
    doomed = [swap_bytes(k, me.rename) for k in other.stripped + other.trashed]
    doomed += me.trashed + me.stripped
    for k in doomed:
        cur = drop_header(cur, k)
    if other.rename:
        cur = remap_header_names(cur, other.rename)
    cur.headers.sort()
    return cur


def judge(a: list[Msg], b: list[Msg], ha: Host, hb: Host) -> Verdict:
    if ha.no_keepalive or hb.no_keepalive:
        a, b = a[:1], b[:1]
    for x, y in itertools.zip_longest(a, b):
        if isinstance(x, Req) and not x.looks_valid():
            return Verdict.INVALID
        if isinstance(y, Req) and not y.looks_valid():
            return Verdict.INVALID
        # one side silent, other sent non-200 error -> treat as agree
        if (x is None and isinstance(y, Resp) and y.code != b"200") or (
            y is None and isinstance(x, Resp) and x.code != b"200"
        ):
            break
        if (x is None or y is None) and x is not y:
            return Verdict.STREAM_DISCREPANCY
        if isinstance(x, Req) != isinstance(y, Req):
            # benign 0.9 mismatch
            if (
                isinstance(x, Req)
                and x.version == b"0.9"
                and isinstance(y, Resp)
                and not hb.allow_09
            ):
                break
            if (
                isinstance(y, Req)
                and y.version == b"0.9"
                and isinstance(x, Resp)
                and not hb.allow_09
            ):
                # NOTE: upstream checks s2 twice here (likely typo); we keep it
                # for byte-identical output.
                break
            # missing length on POST
            if (
                isinstance(x, Resp)
                and x.code == b"411"
                and ha.need_len_post
                and isinstance(y, Req)
                and y.method == b"POST"
                and not hb.need_len_post
            ) or (
                isinstance(y, Resp)
                and y.code == b"411"
                and hb.need_len_post
                and isinstance(x, Req)
                and x.method == b"POST"
                and not ha.need_len_post
            ):
                break
            # missing host header
            if (
                (x is None or (isinstance(x, Resp) and x.code == b"400"))
                and not ha.missing_host_ok
                and isinstance(y, Req)
                and hb.missing_host_ok
                and not y.has(b"host")
            ) or (
                (y is None or (isinstance(y, Resp) and y.code == b"400"))
                and not hb.missing_host_ok
                and isinstance(x, Req)
                and ha.missing_host_ok
                and not x.has(b"host")
            ):
                break
            # method whitelist
            if (
                ha.method_only is not None
                and isinstance(x, Resp)
                and isinstance(y, Req)
                and y.method not in ha.method_only
            ) or (
                hb.method_only is not None
                and isinstance(y, Resp)
                and isinstance(x, Req)
                and x.method not in hb.method_only
            ):
                break
            # method char ban
            if (
                isinstance(x, Resp)
                and isinstance(y, Req)
                and any(c in ha.method_ban for c in y.method)
            ) or (
                isinstance(y, Resp)
                and isinstance(x, Req)
                and any(c in hb.method_ban for c in x.method)
            ):
                break
            return Verdict.TYPE_DISCREPANCY
        if isinstance(x, Resp) and isinstance(y, Resp):
            if x != y:
                return Verdict.RESPONSE_DISCREPANCY
        if isinstance(x, Req) and isinstance(y, Req):
            if scrub(x, ha, hb) != scrub(y, hb, ha):
                return Verdict.REQUEST_DISCREPANCY
    return Verdict.OK
