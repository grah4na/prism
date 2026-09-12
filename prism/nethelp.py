from __future__ import annotations

import multiprocessing.pool
import socket
import ssl
from collections.abc import Callable, Iterator, Sequence
from typing import TypeVar

CHUNK = 0x10000

T = TypeVar("T")
U = TypeVar("U")


def pop_next(it: Iterator[T]) -> T | None:
    try:
        return next(it)
    except StopIteration:
        return None


def wrap_tls(
    sock: socket.socket, host: str, alpn: list[str] | None = None
) -> socket.socket:
    ctx = ssl._create_unverified_context()
    if alpn is not None:
        ctx.set_alpn_protocols(alpn)
    return ctx.wrap_socket(sock, server_hostname=host)


def drain(sock: socket.socket) -> bytes:
    out = b""
    while True:
        try:
            piece = sock.recv(CHUNK)
        except TimeoutError:
            break
        # Some stacks raise socket.timeout (== TimeoutError alias) - covered.
        # Empty means peer closed.
        out += piece
        if len(piece) == 0:
            break
    return out


def exchange(sock: socket.socket, pieces: list[bytes]) -> list[bytes]:
    got: list[bytes] = []
    try:
        for one in pieces:
            sock.sendall(one)
            got.append(drain(sock))
        tail = drain(sock)
        if tail:
            got.append(tail)
    except (
        ssl.SSLEOFError,
        ConnectionRefusedError,
        BrokenPipeError,
        OSError,
        BlockingIOError,
        ConnectionResetError,
    ):
        pass
    return got


def run_parallel(fn: Callable[[U], T], items: Sequence[U]) -> list[T]:
    with multiprocessing.pool.ThreadPool(multiprocessing.cpu_count()) as pool:
        return list(pool.map(fn, items))


def swap_bytes(blob: bytes, table: dict[bytes, bytes]) -> bytes:
    out = blob
    for old, new in table.items():
        out = out.replace(old, new)
    return out
