"""Interactive shell - same commands/output as Prism, fresh code."""

from __future__ import annotations

import shlex
import sys
from typing import Any

from . import h2mini
from .hosts import Host, load_hosts
from .models import Msg, Req, Resp
from .nethelp import pop_next, run_parallel
from .pretty import (
    show_groups,
    show_matrix,
    show_raw,
    show_stream,
    show_views,
)
from .table import build_groups, build_matrix

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


def _is_views(v: Any) -> bool:
    ok = (
        isinstance(v, list)
        and all(isinstance(inner, list) for inner in v)
        and all(all(isinstance(m, (Req, Resp)) for m in inner) for inner in v)
    )
    if not ok:
        print("This command expects to have its input piped in from `fanout`.")
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


def main() -> None:
    try:
        origins, proxies, _all = load_hosts()
    except Exception as e:
        print(f"Failed to load hosts: {e}", file=sys.stderr)
        origins, proxies, _all = {}, {}, {}

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
                elif cmd in (["exit"], ["quit"]):
                    print("Next time, just press Ctrl-D :)")
                    sys.exit(0)
                else:
                    print("Invalid syntax.")
