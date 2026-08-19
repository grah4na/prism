"""Grid / cluster builders."""

from __future__ import annotations

from .hosts import Host
from .models import Msg
from .scoring import Verdict, judge

Matrix = tuple[tuple[Verdict | None, ...], ...]
Groups = tuple[tuple[Host, ...], ...]


def build_matrix(rows: list[list[Msg]], hosts: list[Host]) -> Matrix:
    out: list[tuple[Verdict | None, ...]] = []
    for i, (ha, pa) in enumerate(zip(hosts, rows)):
        line: list[Verdict | None] = []
        for j, (hb, pb) in enumerate(zip(hosts, rows)):
            if j < i:
                line.append(None)
            else:
                line.append(judge(pa, pb, ha, hb))
        out.append(tuple(line))
    return tuple(out)


def build_groups(rows: list[list[Msg]], hosts: list[Host]) -> Groups:
    buckets: list[list[tuple[Host, list[Msg]]]] = []
    for view, host in zip(rows, hosts):
        for bucket in buckets:
            ok_all = all(judge(view, pv, host, hv) == Verdict.OK for hv, pv in bucket)
            bad_all = all(
                judge(view, pv, host, hv) == Verdict.INVALID for hv, pv in bucket
            )
            if ok_all or bad_all:
                bucket.append((host, view))
                break
        else:
            buckets.append([(host, view)])
    return tuple(tuple(h for h, _ in b) for b in buckets)


def squash(m: Matrix) -> Matrix:
    flat: list[list[Verdict | None]] = []
    for row in m:
        line: list[Verdict | None] = []
        for cell in row:
            if cell == Verdict.RESPONSE_DISCREPANCY:
                line.append(Verdict.OK)
            elif cell in (
                Verdict.REQUEST_DISCREPANCY,
                Verdict.TYPE_DISCREPANCY,
                Verdict.STREAM_DISCREPANCY,
                Verdict.INVALID,
            ):
                line.append(Verdict.DISCREPANCY)
            else:
                line.append(cell)
        flat.append(line)
    return tuple(tuple(r) for r in flat)
