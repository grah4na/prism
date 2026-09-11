"""Service discovery + roundtrips (own code, compatible behavior)."""

from __future__ import annotations

import dataclasses
import re
import socket
import sys
from pathlib import Path
from typing import Any

import yaml

from . import h2mini
from .http_parse import (
    decode_trace,
    read_09_reply,
    read_request_stream,
    read_response,
    trim_09,
)
from .models import Msg
from .nethelp import exchange, wrap_tls

ORIGIN_WAIT = 0.05
PROXY_WAIT = 0.5
NET = "http-prism_default"

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent


def _pick(*names: Path) -> Path:
    for p in names:
        if p.exists():
            return p
    return names[0]


_COMPOSE = _pick(_ROOT / "config" / "compose.yml", _ROOT / "docker-compose.yml")
_EXTERNAL = _pick(_ROOT / "config" / "external.yml", _ROOT / "external-services.yml")
_QUIRKS = _pick(_ROOT / "config" / "quirks.yml", _ROOT / "quirks.yml")


@dataclasses.dataclass
class Host:
    name: str
    container: Any | None
    addr: str
    port: int
    tls: bool
    wait: float
    # quirks
    allow_09: bool = False
    allow_h2: bool = False
    extra_headers: list[bytes] = dataclasses.field(default_factory=list)
    need_len_post: bool = False
    missing_host_ok: bool = False
    rename: dict[bytes, bytes] = dataclasses.field(default_factory=dict)
    no_version: bool = False
    method_ban: bytes = b""
    method_only: list[bytes] | None = None
    stripped: list[bytes] = dataclasses.field(default_factory=list)
    trashed: list[bytes] = dataclasses.field(default_factory=list)
    no_keepalive: bool = False
    strict_host: bool = False
    join_dup: bool = False
    join_glue: bytes = b""

    def raw_hit(self, pieces: list[bytes]) -> list[bytes]:
        raise NotImplementedError

    def cooked_hit(self, pieces: list[bytes]) -> list[bytes]:
        raise NotImplementedError

    def parsed_hit(self, pieces: list[bytes]) -> list[Msg]:
        raise NotImplementedError


def _fix_host(pieces: list[bytes], addr: bytes) -> list[bytes]:
    return [
        re.sub(rb"host:[^\n]*\n", b"host: " + addr + b"\r\n", p, flags=re.IGNORECASE)
        for p in pieces
    ]


class Origin(Host):
    def raw_hit(self, pieces: list[bytes]) -> list[bytes]:
        if self.strict_host:
            pieces = _fix_host(pieces, self.addr.encode("latin1"))
        try:
            with socket.create_connection((self.addr, self.port)) as s:
                sock: socket.socket = s
                if self.tls:
                    sock = wrap_tls(sock, self.addr)
                sock.settimeout(self.wait)
                return exchange(sock, pieces)
        except ConnectionRefusedError as e:
            raise ConnectionRefusedError(f"Connection to {self.name} refused") from e

    cooked_hit = raw_hit  # origins echo raw bytes; transducer overrides below

    def parsed_hit(self, pieces: list[bytes]) -> list[Msg]:
        blob = b"".join(self.raw_hit(pieces))
        out: list[Msg] = []
        while blob:
            got: Msg | None = None
            leftover = b""
            try:
                resp, leftover = read_response(blob)
                if resp.code != b"200":
                    got = resp
                else:
                    got = decode_trace(resp.body)
            except ValueError:
                pass
            if got is None and self.allow_h2:
                try:
                    frames = h2mini.scan_all(blob)
                    payload = b"".join(
                        f.payload for f in frames if int(f.typ) == h2mini.DATA
                    )
                    got = decode_trace(payload)
                    leftover = b""
                except Exception:
                    pass
            if got is None and self.allow_09:
                try:
                    got = decode_trace(trim_09(blob))
                    leftover = b""
                    # match upstream: stop after 0.9-json path
                    out.append(got)
                    break
                except ValueError:
                    pass
                try:
                    got = read_09_reply(trim_09(blob))
                    leftover = b""
                except ValueError:
                    pass
            if got is None:
                print(
                    f"Couldn't parse {self.name}'s response to {pieces!r}:\n    {blob!r}",
                    file=sys.stderr,
                )
                leftover = b""
            else:
                # avoid double-append from early break above
                if not out or out[-1] is not got:
                    out.append(got)
            blob = leftover
        return out


class Proxy(Host):
    def raw_hit(self, pieces: list[bytes]) -> list[bytes]:
        if self.strict_host:
            pieces = _fix_host(pieces, self.addr.encode("latin1"))
        try:
            with socket.create_connection((self.addr, self.port)) as s:
                sock: socket.socket = s
                if self.tls:
                    sock = wrap_tls(sock, self.addr)
                sock.settimeout(self.wait)
                out = exchange(sock, pieces)
                try:
                    sock.close()
                except OSError:
                    pass
                return out
        except ConnectionRefusedError as e:
            raise ConnectionRefusedError(f"Connection to {self.name} refused") from e

    def cooked_hit(self, pieces: list[bytes]) -> list[bytes]:
        blob = b"".join(self.raw_hit(pieces))
        chunks: list[bytes] = []
        resp = None
        while blob:
            try:
                resp, rest = read_response(blob)
            except ValueError:
                if resp is None:
                    chunks.append(trim_09(blob))
                    break
                # keep upstream quirk: fall through with old resp
                rest = b""
            if resp is not None and resp.code == b"200":
                chunks.append(resp.body)
            elif resp is not None:
                chunks.append(blob[: len(blob) - len(rest)])
            blob = rest
            if not blob:
                break
        return chunks

    def parsed_hit(self, pieces: list[bytes]) -> list[Msg]:
        reqs, extra = read_request_stream(b"".join(self.cooked_hit(pieces)))
        if extra:
            print(
                f"{self.name!r} left some extra data on the end of the request stream: {extra!r}",
                file=sys.stderr,
            )
        return list(reqs)


def _container_ips(net: str) -> dict[str, Any]:
    try:
        import docker

        client = docker.from_env()
        found = client.networks.get(net).containers
        return {c.labels.get("com.docker.compose.service", ""): c for c in found}
    except Exception:
        return {}


def _ip_of(cont: Any | None, net: str) -> str | None:
    if cont is None:
        return None
    try:
        return cont.attrs["NetworkSettings"]["Networks"][net]["IPAddress"]
    except Exception:
        return None


def load_hosts() -> tuple[dict[str, Origin], dict[str, Proxy], dict[str, Host]]:
    with open(_QUIRKS, encoding="latin1") as f:
        quirks: dict = yaml.safe_load(f) or {}
    with open(_COMPOSE, encoding="latin1") as f:
        internal: dict = yaml.safe_load(f).get("services", {}) or {}
    try:
        with open(_EXTERNAL, encoding="latin1") as f:
            external: dict = yaml.safe_load(f) or {}
    except FileNotFoundError:
        external = {}
    merged: dict = {**internal, **external}

    cmap = _container_ips(NET)
    missing: list[str] = []
    found: list[Host] = []

    for svc, cfg in merged.items():
        xp: dict[str, Any] = (cfg or {}).get("x-props", {}) or {}
        role = xp.get("role")
        cls = Origin if role == "origin" else Proxy if role == "transducer" else None
        cont = cmap.get(svc)
        if cls is not None and cont is None and svc not in external:
            missing.append(svc)
            continue
        addr = xp.get("address", _ip_of(cont, NET))
        if not isinstance(addr, str):
            continue
        q: dict = quirks.get(svc, {}) or {}
        need_tls = bool(xp.get("requires-tls", False))
        default_wait = ORIGIN_WAIT if role == "origin" else PROXY_WAIT
        kw = dict(
            name=svc,
            container=cont,
            addr=addr,
            port=int(xp.get("port", 443 if need_tls else 80)),
            tls=need_tls,
            wait=float(xp.get("timeout") or default_wait),
            allow_09=bool(q.get("allows-http-0-9", False)),
            allow_h2=bool(q.get("allows-http-2", False)),
            extra_headers=[k.encode("latin1") for k in q.get("added-headers", [])],
            need_len_post=bool(q.get("requires-length-in-post", False)),
            missing_host_ok=bool(q.get("allows-missing-host-header", False)),
            rename={
                k.encode("latin1"): v.encode("latin1")
                for k, v in (q.get("header-name-translation", {}) or {}).items()
            },
            no_version=bool(q.get("doesnt-support-version", False)),
            method_only=(
                [s.encode("latin1") for s in q.get("method-whitelist", [])] or None
            ),
            method_ban=q.get("method-character-blacklist", "").encode("latin1"),
            stripped=[k.encode("latin1") for k in q.get("removed-headers", [])],
            trashed=[k.encode("latin1") for k in q.get("trashed-headers", [])],
            no_keepalive=bool(q.get("doesnt-support-persistence", False)),
            strict_host=bool(q.get("requires-specific-host-header", False)),
            join_dup=bool(q.get("joins-duplicate-headers", False)),
            join_glue=q.get("duplicate-header-joiner", "").encode("latin1"),
        )
        assert cls is not None
        found.append(cls(**kw))

    if missing:
        print(
            f"Warning: {', '.join(missing)} container(s) not running!", file=sys.stderr
        )

    found.sort(key=lambda h: h.name)
    origins = {h.name: h for h in found if isinstance(h, Origin)}
    proxies = {h.name: h for h in found if isinstance(h, Proxy)}
    allh = {h.name: h for h in found if isinstance(h, (Origin, Proxy))}
    return origins, proxies, allh
