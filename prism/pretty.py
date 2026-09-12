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


def show_resp_full(r: Resp) -> None:
    """Render one raw reply envelope (status line, headers, body snippet)."""
    print(
        f"    {RED}HTTPResponse{OFF}(version={r.version!r}, code={r.code!r}, reason={r.reason!r}),"
    )
    if not r.headers:
        print("        headers=[],")
    else:
        print("        headers=[")
        for k, v in r.headers:
            print(f"            ({k!r}, {v!r}),")
        print("        ],")
    body = r.body
    if len(body) > 80:
        body = body[:80] + b"..."
    print(f"        body={body!r},")
    print("    ),")


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


def show_resp_matrix(m: Matrix, names: list[str]) -> None:
    """Like show_matrix, but a differing response is a real discrepancy (X)."""
    width = max(map(len, names))
    padded = [n.ljust(width) for n in names]
    head_src = [" " * len(padded[0]), *padded]
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
            elif cell == Verdict.OK:
                mark = f"{GREEN}\u2713{OFF}"
            elif cell in (
                Verdict.DISCREPANCY,
                Verdict.REQUEST_DISCREPANCY,
                Verdict.TYPE_DISCREPANCY,
                Verdict.STREAM_DISCREPANCY,
                Verdict.RESPONSE_DISCREPANCY,
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


# ---------- help text (no upstream equivalent; ours only) ----------

# topic -> (syntax, short blurb, long description, example)
HELP_TOPICS: dict[str, tuple[str, str, str, str]] = {
    "payload": (
        "payload '<bytes>' [...]",
        "Start a pipeline with raw bytes",
        "Build the byte stream that later stages send. Escape special bytes "
        "as \\r \\n \\xff. Bare `payload` prints the current bytes instead.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout",
    ),
    "h2frames": (
        "h2frames [ pri ] [ frame ... ]",
        "Build raw HTTP/2 wire bytes",
        "Each frame is [ type <t> flags { ... } id <n> payload '<bytes>' ]. "
        "Types: data headers priority rst_stream settings push_promise ping "
        "goaway window_update continuation (or a number 0-255).",
        "h2frames pri [ type settings flags { 0 } id 0 payload '' ] | h2fanout",
    ),
    "h3frames": (
        "h3frames [ frame ... ]",
        "Build raw HTTP/3 frame bytes",
        "Each frame is [ type <t> payload '<bytes>' ]. Types: data headers "
        "cancel_push settings push_promise goaway max_push_id (or a number "
        "0-255). QUIC varints are handled for you.",
        "h3frames [ type headers payload '\\x00\\x00' ] [ type data payload '' ]",
    ),
    "h3fanout": (
        "h3fanout [server ...]",
        "Fanout to HTTP/3 servers only",
        "Send the current request bytes to HTTP/3 origins over QUIC and show "
        "each decoded reply. Input comes from `payload` (a plain HTTP/1 request "
        "line). Defaults to all H3 origins. Requires the optional aioquic "
        "dependency.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | h3fanout",
    ),
    "transduce": (
        "transduce <proxy> [...]",
        "Rewrite bytes through proxies",
        "Pipe the current bytes through one or more transducer proxies, "
        "printing the bytes after each hop.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | transduce squid | fanout",
    ),
    "fanout": (
        "fanout [server ...]",
        "Send bytes, show parsed replies",
        "Send the current bytes to origin servers and show each parsed "
        "request/response. Defaults to all origins.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout nginx apache_httpd",
    ),
    "h2fanout": (
        "h2fanout [server ...]",
        "Fanout to HTTP/2 servers only",
        "Like fanout, but only hits servers that accept HTTP/2.",
        "h2frames pri [ type settings flags { 0 } id 0 payload '' ] | h2fanout",
    ),
    "unparsed_fanout": (
        "unparsed_fanout | uf [server ...]",
        "Send bytes, show raw replies",
        "Send the current bytes to origin servers and show the raw reply "
        "bytes without parsing them.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | uf nginx",
    ),
    "unparsed_transducer_fanout": (
        "unparsed_transducer_fanout | utf [proxy ...]",
        "Raw replies from proxies",
        "Send the current bytes to transducer proxies and show the raw "
        "reply bytes without parsing them.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | utf squid",
    ),
    "grid": (
        "fanout ... | grid [server ...]",
        "Pairwise comparison matrix",
        "Compare parsed fanout views pairwise into a difference matrix. "
        "Ends the pipeline.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout | grid",
    ),
    "cluster": (
        "fanout ... | cluster [server ...]",
        "Group identical servers",
        "Group servers that parsed the fanout views identically. " "Ends the pipeline.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout | cluster",
    ),
    "rfanout": (
        "rfanout [server ...]",
        "Send bytes, show reply envelopes",
        "Send the current bytes to origins and transducers and show each reply "
        "as an HTTP response envelope (status, headers, body) instead of the "
        "parsed request trace. Defaults to every server.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | rfanout reactphp busybox",
    ),
    "rgrid": (
        "rfanout ... | rgrid [server ...]",
        "Pairwise comparison of replies",
        "Compare the raw reply envelopes from rfanout pairwise into a "
        "difference matrix. Status, headers and rejection bodies are compared. "
        "Ends the pipeline.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | rfanout | rgrid",
    ),
    "rcluster": (
        "rfanout ... | rcluster [server ...]",
        "Group servers that replied alike",
        "Group servers whose raw reply envelopes compare equal. " "Ends the pipeline.",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | rfanout | rcluster",
    ),
    "help": (
        "help [command]",
        "Show this help",
        "Print the command overview, or usage and an example for one command.",
        "help fanout",
    ),
    "examples": (
        "help examples",
        "Copy-paste example payloads",
        "Ready-made pipelines to paste at the prompt. Swap grid for cluster "
        "to regroup, or add server names to narrow the run.",
        "",
    ),
    "exit": (
        "exit | quit",
        "Leave the shell",
        "Leave the shell (Ctrl-D works too).",
        "exit",
    ),
}

# short names share the full topic
HELP_TOPICS["uf"] = HELP_TOPICS["unparsed_fanout"]
HELP_TOPICS["utf"] = HELP_TOPICS["unparsed_transducer_fanout"]
HELP_TOPICS["quit"] = HELP_TOPICS["exit"]

_HELP_GROUPS: list[tuple[str, list[str]]] = [
    ("START A PIPELINE", ["payload", "h2frames", "h3frames"]),
    (
        "REWRITE & SEND",
        [
            "transduce",
            "fanout",
            "h2fanout",
            "h3fanout",
            "unparsed_fanout",
            "unparsed_transducer_fanout",
            "rfanout",
        ],
    ),
    ("COMPARE & VIEW", ["grid", "cluster", "rgrid", "rcluster"]),
    ("SESSION", ["help", "examples", "exit"]),
]

# (label, full pipeline to paste) shown by `help examples`
_EXAMPLE_PAYLOADS: list[tuple[str, str]] = [
    (
        "Basic GET",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout | grid",
    ),
    (
        "POST with body",
        "payload 'POST / HTTP/1.1\\r\\nHost: a\\r\\nContent-Length: 5\\r\\n\\r\\nhello' "
        "| fanout | grid",
    ),
    (
        "Chunked POST",
        "payload 'POST / HTTP/1.1\\r\\nHost: a\\r\\nTransfer-Encoding: chunked\\r\\n\\r\\n"
        "4\\r\\nWiki\\r\\n0\\r\\n\\r\\n' | fanout | grid",
    ),
    (
        "Missing Host header",
        "payload 'GET / HTTP/1.1\\r\\n\\r\\n' | fanout | grid",
    ),
    (
        "HTTP/1.0 without headers",
        "payload 'GET / HTTP/1.0\\r\\n\\r\\n' | fanout | grid",
    ),
    (
        "Duplicate headers",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\nX: 1\\r\\nX: 2\\r\\n\\r\\n' "
        "| fanout | grid",
    ),
    (
        "Absolute URI",
        "payload 'GET http://a/ HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | fanout | grid",
    ),
    (
        "HTTP/2 preface + settings",
        "h2frames pri [ type settings flags { 0 } id 0 payload '' ] | h2fanout",
    ),
    (
        "Response direction",
        "payload 'GET / HTTP/1.1\\r\\nHost: a\\r\\n\\r\\n' | rfanout | rgrid",
    ),
]


def _help_columns() -> int:
    try:
        import shutil

        return max(40, shutil.get_terminal_size((80, 24)).columns)
    except Exception:
        return 80


def _help_wrap(text: str, indent: str) -> list[str]:
    import textwrap

    return textwrap.wrap(
        text,
        width=_help_columns(),
        initial_indent=indent,
        subsequent_indent=indent,
    )


def show_help(topic: str | None = None) -> None:
    if topic is not None:
        key = topic.lower()
        if key in ("unparsed-fanout",):
            key = "unparsed_fanout"
        if key in ("unparsed-transducer-fanout",):
            key = "unparsed_transducer_fanout"
        if key not in HELP_TOPICS:
            print(f"Unknown help topic: {topic}")
            print(
                "Topics: payload h2frames h3frames transduce fanout h2fanout h3fanout "
                "unparsed_fanout|uf unparsed_transducer_fanout|utf "
                "grid cluster rfanout rgrid rcluster help examples exit|quit"
            )
            return
        if key == "examples":
            _, short, what, _ = HELP_TOPICS[key]
            print(f"{BLUE}examples{OFF} -- {short}")
            print()
            print(*_help_wrap(what, "  "), sep="\n")
            for label, cmd in _EXAMPLE_PAYLOADS:
                print()
                print(f"  {GREEN}{label}{OFF}")
                print(f"    {cmd}")
            return
        syntax, short, what, example = HELP_TOPICS[key]
        print(f"{BLUE}{key}{OFF} -- {short}")
        print()
        print(f"  Syntax   {syntax}")
        print(f"  Example  {example}")
        print()
        print(*_help_wrap(what, "  "), sep="\n")
        return
    print("Prism commands -- chain stages with `|`, run several with `;`.")
    for title, names in _HELP_GROUPS:
        print()
        print(f"  {GREEN}{title}{OFF}")
        width = max(len(n) for n in names)
        for name in names:
            _, short, _, _ = HELP_TOPICS[name]
            print(f"    {BLUE}{name.ljust(width)}{OFF}  {short}")
    print()
    print("  Type `help <command>` for usage and an example.")
