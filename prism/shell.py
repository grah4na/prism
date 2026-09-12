"""Interactive shell - same commands/output as Prism, fresh code."""

from __future__ import annotations

import shlex
import sys
from typing import Any, cast

from . import h2mini, h3mini, quichelp
from .hosts import Host, load_hosts
from .http_parse import read_request
from .models import Msg, Req, Resp
from .nethelp import pop_next, run_parallel
from .pretty import (
    show_groups,
    show_help,
    show_matrix,
    show_raw,
    show_resp_full,
    show_resp_matrix,
    show_stream,
    show_views,
)
from .table import (
    build_groups,
    build_matrix,
    build_response_groups,
    build_response_matrix,
)

PROMPT = "\x1b[0;32mprism>\x1b[0m "


class ShellErr(Exception):
    pass


# ---------- H2 frame DSL (mirrors Prism messages) ----------


def _ftype_word(it) -> h2mini.FType:
    it = iter(it)
    tok = pop_next(it)
    if tok is None:
        raise ShellErr("Unexpected start of type statement")
    low = tok.lower()
    table = {
        "data": 0,
        "headers": 1,
        "priority": 2,
        "rst_stream": 3,
        "settings": 4,
        "push_promise": 5,
        "ping": 6,
        "goaway": 7,
        "window_update": 8,
        "continuation": 9,
    }
    if low in table:
        return h2mini.FType(table[low])
    try:
        num = int(tok)
    except ValueError:
        raise ShellErr("Unexpected value of type statement")
    if num not in range(256):
        raise ShellErr("type out of range!")
    return h2mini.FType(num)


def _flags_word(it) -> h2mini.FFlags:
    it = iter(it)
    first = pop_next(it)
    if first is None or first.lower() != "{":
        raise ShellErr("Unexpected start of flags statement (should begin with '{')!")
    bits = 0
    while True:
        tok = pop_next(it)
        if tok is None:
            raise ShellErr("Unexpected end of flags statement!")
        t = tok.lower()
        if t in ("0", "end_stream", "ack"):
            bits |= 1 << 0
        elif t == "1":
            bits |= 1 << 1
        elif t in ("2", "end_headers"):
            bits |= 1 << 2
        elif t in ("3", "padded"):
            bits |= 1 << 3
        elif t == "4":
            bits |= 1 << 4
        elif t in ("5", "priority"):
            bits |= 1 << 5
        elif t == "6":
            bits |= 1 << 6
        elif t == "7":
            bits |= 1 << 7
        elif t == "}":
            break
        else:
            raise ShellErr("Unexpected value of flags statement")
    return h2mini.FFlags.decode(bits)


def _frames_word(words: list[str]) -> list[bytes]:
    it = iter(words)
    out: list[bytes] = []
    while True:
        typ: h2mini.FType | None = None
        flg = h2mini.FFlags()
        rsv = False
        sid = 0
        body = b""
        head = pop_next(it)
        if head is None:
            break
        if head.lower() == "pri":
            out.append(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
            continue
        if head.lower() != "[":
            raise ShellErr(
                "Unexpected start of frame statement (should begin with '[')!"
            )
        while True:
            tok = pop_next(it)
            if tok is None:
                raise ShellErr("Unexpected end of frame statement!")
            t = tok.lower()
            if t == "type":
                typ = _ftype_word(it)
            elif t == "flags":
                flg = _flags_word(it)
            elif t in ("id", "stream_id"):
                raw = pop_next(it)
                if raw is None:
                    raise ShellErr("Premature end of stream_id statement!")
                try:
                    sid = int(raw)
                except ValueError:
                    raise ShellErr("Invalid stream_id")
            elif t == "reserved":
                rsv = True
            elif t == "payload":
                raw = pop_next(it)
                if raw is None:
                    raise ShellErr("Premature end of payload statement!")
                try:
                    body = (
                        raw.encode("latin1").decode("unicode-escape").encode("latin1")
                    )
                except UnicodeEncodeError:
                    raise ShellErr(
                        "Couldn't encode the frame payload to latin1. If you're using multibyte characters, please use escape sequences (e.g. `\\xff`) instead."
                    )
                except UnicodeDecodeError:
                    raise ShellErr(
                        "Couldn't Unicode escape the frame payload. Did you forget to quote it?"
                    )
            elif t == "]":
                break
        if typ is None:
            raise ShellErr("No valid H2FrameType found!")
        out.append(h2mini.Frame(typ, flg, rsv, sid, body).wire())
    return out


def _h3type_word(it) -> h3mini.FType:
    it = iter(it)
    tok = pop_next(it)
    if tok is None:
        raise ShellErr("Unexpected start of type statement")
    low = tok.lower()
    table = {
        "data": h3mini.DATA,
        "headers": h3mini.HEADERS,
        "cancel_push": h3mini.CANCEL_PUSH,
        "settings": h3mini.SETTINGS,
        "push_promise": h3mini.PUSH_PROMISE,
        "goaway": h3mini.GOAWAY,
        "max_push_id": h3mini.MAX_PUSH_ID,
    }
    if low in table:
        return h3mini.FType(table[low])
    try:
        num = int(tok)
    except ValueError:
        raise ShellErr("Unexpected value of type statement")
    if num not in range(256):
        raise ShellErr("type out of range!")
    return h3mini.FType(num)


def _h3frames_word(words: list[str]) -> list[bytes]:
    it = iter(words)
    out: list[bytes] = []
    while True:
        head = pop_next(it)
        if head is None:
            break
        if head.lower() != "[":
            raise ShellErr(
                "Unexpected start of frame statement (should begin with '[')!"
            )
        typ: h3mini.FType | None = None
        payload = b""
        while True:
            tok = pop_next(it)
            if tok is None:
                raise ShellErr("Unexpected end of frame statement!")
            t = tok.lower()
            if t == "type":
                typ = _h3type_word(it)
            elif t == "payload":
                raw = pop_next(it)
                if raw is None:
                    raise ShellErr("Premature end of payload statement!")
                try:
                    payload = (
                        raw.encode("latin1").decode("unicode-escape").encode("latin1")
                    )
                except UnicodeEncodeError:
                    raise ShellErr(
                        "Couldn't encode the frame payload to latin1. If you're using multibyte characters, please use escape sequences (e.g. `\\xff`) instead."
                    )
                except UnicodeDecodeError:
                    raise ShellErr(
                        "Couldn't Unicode escape the frame payload. Did you forget to quote it?"
                    )
            elif t == "]":
                break
        if typ is None:
            raise ShellErr("No valid H3FrameType found!")
        out.append(h3mini.Frame(typ, payload).wire())
    return out


# ---------- validation helpers (same wording) ----------


def _ok_hosts(names: list[str], origins, proxies) -> bool:
    for n in names:
        if n not in origins and n not in proxies:
            print(f"Invalid server name: {n}")
            return False
    return True


def _ok_proxy(names: list[str], proxies) -> bool:
    for n in names:
        if n not in proxies:
            print(
                f"Invalid server name: {n}"
                if False
                else f"Invalid transducer name: {n}"
            )
            return False
    return True


def _ok_origin(names: list[str], origins) -> bool:
    for n in names:
        if n not in origins:
            print(f"Invalid origin name: {n}")
            return False
    return True


def _ok_h3(names: list[str], h3hosts) -> bool:
    for n in names:
        if n not in h3hosts:
            print(f"Invalid H3 server name: {n}")
            return False
    return True


def _ok_resp_hosts(names: list[str], origins, proxies, h3hosts) -> bool:
    for n in names:
        if n not in origins and n not in proxies and n not in h3hosts:
            print(f"Invalid server name: {n}")
            return False
    return True


def _h3_fields(req: Req) -> list[tuple[bytes, bytes]]:
    authority = b""
    for k, v in req.headers:
        if k.lower() == b"host":
            authority = v
            break
    fields = [
        (b":method", req.method),
        (b":scheme", b"https"),
        (b":authority", authority),
        (b":path", req.uri),
    ]
    fields += [(k, v) for k, v in req.headers if k.lower() != b"host"]
    return fields


def _is_views(v: Any) -> bool:
    ok = (
        isinstance(v, list)
        and all(isinstance(inner, list) for inner in v)
        and all(all(isinstance(m, (Req, Resp)) for m in inner) for inner in v)
    )
    if not ok:
        print("This command expects to have its input piped in from `fanout`.")
    return ok


def _is_resp_views(v: Any) -> bool:
    ok = (
        isinstance(v, list)
        and all(isinstance(inner, list) for inner in v)
        and all(all(isinstance(m, Resp) for m in inner) for inner in v)
    )
    if not ok:
        print("This command expects to have its input piped in from `rfanout`.")
    return ok


def _is_bytes(v: Any) -> bool:
    return isinstance(v, list) and all(isinstance(x, bytes) for x in v)


def _split(items: list[str], sep: str) -> list[list[str]]:
    parts: list[list[str]] = []
    cur: list[str] = []
    for t in items:
        if t == sep:
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    return parts


def _decode_payload(symbols: list[str]) -> list[bytes]:
    return [
        s.encode("latin1").decode("unicode-escape").encode("latin1") for s in symbols
    ]


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] in ("--help", "-h", "help"):
        show_help(args[1] if len(args) == 2 else None)
        return
    try:
        origins, proxies, allhosts, h3hosts = load_hosts()
    except Exception as e:
        print(f"Failed to load hosts: {e}", file=sys.stderr)
        origins, proxies, allhosts, h3hosts = {}, {}, {}, {}

    resp_hosts = {**allhosts, **h3hosts}
    last_hosts: list[str] = []

    while True:
        try:
            line = input(PROMPT)
        except EOFError:
            break
        except KeyboardInterrupt:
            print()
            continue

        try:
            lexed = [
                t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t
                for t in shlex.shlex(line)
            ]
        except ValueError:
            print("Couldn't lex the line! Are your quotes matched?")
            continue

        for pipeline in [_split(p, "|") for p in _split(lexed, ";")]:
            cur: None | list[bytes] | list[list[Msg]] = None
            for cmd in pipeline:
                if cmd == []:
                    pass
                elif cmd == ["payload"]:
                    print(cur)
                elif cmd and cmd[0] == "payload":
                    try:
                        cur = _decode_payload(cmd[1:])
                    except UnicodeEncodeError:
                        print(
                            "Couldn't encode the payload to latin1. If you're using multibyte characters, please use escape sequences (e.g. `\\xff`) instead."
                        )
                    except UnicodeDecodeError:
                        print(
                            "Couldn't Unicode escape the payload. Did you forget to quote it?"
                        )
                elif cmd and cmd[0] == "grid":
                    if _is_views(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(origins.keys())
                        if _ok_hosts(want, origins, proxies) and want:
                            show_matrix(
                                build_matrix(cur, [origins[n] for n in want]), want
                            )
                        cur = None
                elif cmd and cmd[0] == "cluster":
                    if _is_views(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(origins.keys())
                        if _ok_hosts(want, origins, proxies) and want:
                            show_groups(build_groups(cur, [origins[n] for n in want]))
                        cur = None
                elif cmd and cmd[0] == "rfanout":
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(allhosts.keys())
                        if _ok_hosts(want, origins, proxies) and want:
                            last_hosts = want
                            targets = [allhosts[n] for n in want]
                            rows = run_parallel(lambda h: h.response_hit(cur), targets)  # type: ignore[arg-type]
                            cur = rows  # type: ignore[assignment]
                            for name, items in zip(want, rows):
                                print(f"{name}: [")
                                for it in items:
                                    show_resp_full(it)
                                print("]")
                    else:
                        print(
                            "This command expects to have its input piped in from `payload` or `transduce`."
                        )
                elif cmd and cmd[0] == "rgrid":
                    if _is_resp_views(cur):
                        rows = cast("list[list[Resp]]", cur)
                        want = cmd[1:] or last_hosts or list(allhosts.keys())
                        if _ok_resp_hosts(want, origins, proxies, h3hosts) and want:
                            show_resp_matrix(
                                build_response_matrix(
                                    rows, [resp_hosts[n] for n in want]
                                ),
                                want,
                            )
                        cur = None
                elif cmd and cmd[0] == "rcluster":
                    if _is_resp_views(cur):
                        rows = cast("list[list[Resp]]", cur)
                        want = cmd[1:] or last_hosts or list(allhosts.keys())
                        if _ok_resp_hosts(want, origins, proxies, h3hosts) and want:
                            show_groups(
                                build_response_groups(
                                    rows, [resp_hosts[n] for n in want]
                                )
                            )
                        cur = None
                elif cmd and cmd[0] == "transduce":
                    names = cmd[1:]
                    if names and _ok_proxy(names, proxies):
                        if _is_bytes(cur):
                            assert isinstance(cur, list)
                            show_stream(cur)
                            for n in names:
                                h = proxies[n]
                                cur = h.cooked_hit(cur)
                                print(f"\u2b07\ufe0f \x1b[0;34m{h.name}\x1b[0m")
                                show_stream(cur)
                        else:
                            print(
                                "This command expects to have its input piped in from `payload` or `transduce`."
                            )
                elif cmd and cmd[0] == "fanout":
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(origins.keys())
                        if _ok_hosts(want, origins, proxies):
                            hosts: list[Host] = [origins[n] for n in want]
                            cur = run_parallel(lambda h: h.parsed_hit(list(cur)), hosts)  # type: ignore[arg-type]
                            show_views(cur, want)
                    else:
                        print(
                            "This command expects to have its input piped in from `payload` or `transduce`."
                        )
                elif cmd and cmd[0] == "h2fanout":
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(origins.keys())
                        if _ok_hosts(want, origins, proxies):
                            hosts = [origins[n] for n in want if origins[n].allow_h2]
                            cur = run_parallel(lambda h: h.parsed_hit(list(cur)), hosts)  # type: ignore[arg-type]
                            show_views(cur, want)
                    else:
                        print(
                            "This command expects to have its input piped in from `payload` or `transduce`."
                        )
                elif cmd and cmd[0] in ("unparsed_fanout", "uf"):
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(origins.keys())
                        if _ok_hosts(want, origins, proxies):
                            hosts = [origins[n] for n in want]
                            ans = run_parallel(lambda h: h.raw_hit(list(cur)), hosts)  # type: ignore[arg-type]
                            show_raw(cur, hosts, ans)
                    else:
                        print(
                            "This command expects to have its input piped in from `payload` or `transduce`."
                        )
                elif cmd and cmd[0] in ("unparsed_transducer_fanout", "utf"):
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(proxies.keys())
                        if _ok_proxy(want, proxies):
                            hosts = [proxies[n] for n in want]
                            ans = run_parallel(lambda h: h.raw_hit(list(cur)), hosts)  # type: ignore[arg-type]
                            show_raw(cur, hosts, ans)
                    else:
                        print(
                            "This command expects to have its input piped in from `payload` or `transduce`."
                        )
                elif cmd and cmd[0] == "h2frames":
                    try:
                        blob = b"".join(_frames_word(cmd[1:]))
                        if _is_bytes(cur):
                            assert isinstance(cur, list)
                            cur.append(blob)
                        else:
                            cur = [blob]
                    except ShellErr as e:
                        print(f"repl parse error: {e}")
                elif cmd and cmd[0] == "h3frames":
                    try:
                        blob = b"".join(_h3frames_word(cmd[1:]))
                        if _is_bytes(cur):
                            assert isinstance(cur, list)
                            cur.append(blob)
                        else:
                            cur = [blob]
                    except ShellErr as e:
                        print(f"repl parse error: {e}")
                elif cmd and cmd[0] == "h3fanout":
                    if _is_bytes(cur):
                        assert isinstance(cur, list)
                        want = cmd[1:] or list(h3hosts.keys())
                        if _ok_h3(want, h3hosts) and want:
                            last_hosts = want
                            try:
                                req, _ = read_request(b"".join(cur))
                            except ValueError as e:
                                print(f"Couldn't parse request bytes for h3fanout: {e}")
                            else:
                                fields = _h3_fields(req)
                                hosts = [h3hosts[n] for n in want]
                                rows = run_parallel(
                                    lambda h: [
                                        quichelp.h3_hit(
                                            h.addr, h.port, fields, req.body
                                        ).to_resp()
                                    ],
                                    hosts,
                                )
                                cur = rows  # type: ignore[assignment]
                                for name, items in zip(want, rows):
                                    print(f"{name}: [")
                                    for it in items:
                                        show_resp_full(it)
                                    print("]")
                    else:
                        print(
                            "This command expects to have its input piped in from `payload`."
                        )
                elif cmd and cmd[0] == "help":
                    if len(cmd) > 2:
                        print("Usage: help [command]")
                    else:
                        show_help(cmd[1] if len(cmd) == 2 else None)
                elif cmd in (["exit"], ["quit"]):
                    print("Next time, just press Ctrl-D :)")
                    sys.exit(0)
                else:
                    print("Invalid syntax.")
