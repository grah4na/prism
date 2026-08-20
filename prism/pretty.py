"""Terminal rendering - byte-identical to Prism output."""

from __future__ import annotations

import itertools

from .hosts import Host
from .models import Msg, Req, Resp
from .scoring import Verdict
from .table import Groups, Matrix

BLUE = "\x1b[0;34m"
RED = "\x1b[0;31m"
GREEN = "\x1b[0;32m"
BAD = "\x1b[37;41m"
OFF = "\x1b[0m"


def show_req(r: Req) -> None:
    print(f"    {BLUE}HTTPRequest{OFF}(")
    print(f"        method={r.method!r}, uri={r.uri!r}, version={r.version!r},")
    if not r.headers:
        print("        headers=[],")
    else:
        print("        headers=[")
        for k, v in r.headers:
            print(f"            ({k!r}, {v!r}),")
        print("        ],")
    print(f"        body={r.body!r},")
    print("    ),")


def show_resp(r: Resp) -> None:
    # Upstream labels the code as `method=`; keep it for parity.
    print(
        f"    {RED}HTTPResponse{OFF}(version={r.version!r}, method={r.code!r}, reason={r.reason!r}),"
    )


def show_views(views: list[list[Msg]], names: list[str]) -> None:
    for name, items in zip(names, views):
        print(f"{name}: [")
        for it in items:
            if isinstance(it, Req):
                show_req(it)
            elif isinstance(it, Resp):
                show_resp(it)
        print("]")


def show_raw(
    payload: list[bytes], hosts: list[Host], answers: list[list[bytes]]
) -> None:
    for h, blobs in zip(hosts, answers):
        print(f"{BLUE}{h.name}{OFF}:")
        for b in blobs:
            if b.startswith(b"HTTP/"):
                view = b
                if len(view) > 80:
                    view = view[:80] + b"..."
                print(f"{RED}", end="")
                print(repr(view) + OFF)
            else:
                print(repr(b) + OFF)


def show_matrix(m: Matrix, names: list[str]) -> None:
    width = max(map(len, names))
    padded = [n.ljust(width) for n in names]
    head_src = [" " * len(padded[0]), *padded]
    # vertical labels: same zip_longest trick as upstream
    text = "".join(
        f'{"".ljust(width - 1)}{" ".join(row)}\n'
        for row in itertools.zip_longest(
            *(s.strip().rjust(len(s)) for s in head_src),
        )
    )
    text += f"{''.ljust(width)}+{'-' * (len(names) * 2 - 1)}\n"
    for label, row in zip(padded, m):
        text += label.ljust(width) + "|"
        for cell in row:
            if cell is None:
                mark = " "
            elif cell in (Verdict.OK, Verdict.RESPONSE_DISCREPANCY):
                mark = f"{GREEN}\u2713{OFF}"
            elif cell in (
                Verdict.DISCREPANCY,
                Verdict.REQUEST_DISCREPANCY,
                Verdict.TYPE_DISCREPANCY,
                Verdict.STREAM_DISCREPANCY,
            ):
                mark = f"{RED}X{OFF}"
            elif cell == Verdict.INVALID:
                mark = f"{BAD}X{OFF}"
            else:
                mark = "?"
            text += mark + " "
        text += "\n"
    print(text, end="")


def show_groups(g: Groups) -> None:
    for i, grp in enumerate(g):
        print(f"    {i}.", *(h.name for h in grp))


def show_stream(blobs: list[bytes]) -> None:
    print(" ".join(repr(b)[1:] for b in blobs))
