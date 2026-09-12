"""QUIC + HTTP/3 transport via aioquic (lazy import).

aioquic is optional: it is imported inside the functions so H1/H2 users never
need it installed. aioquic also handles QPACK (via pylsqpack), so this layer
only has to drive the H3 connection and fold the result into H3Reply.
"""

from __future__ import annotations

import asyncio

from .h3mini import H3Reply

DEFAULT_TIMEOUT = 5.0


class H3TransportError(Exception):
    pass


def _require_aioquic() -> None:
    try:
        import aioquic.asyncio.client  # noqa: F401
        import aioquic.h3.connection  # noqa: F401
        import pylsqpack  # noqa: F401
    except ImportError as e:
        raise H3TransportError(
            "HTTP/3 support requires the optional 'aioquic' dependency. "
            "Install it with: uv run --with aioquic python -m prism"
        ) from e


def h3_hit(
    addr: str,
    port: int,
    fields: list[tuple[bytes, bytes]],
    body: bytes = b"",
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> H3Reply:
    """Synchronously send one H3 request and return the decoded reply."""
    _require_aioquic()
    try:
        return asyncio.run(_h3_hit_async(addr, port, fields, body, timeout))
    except H3TransportError:
        raise
    except Exception as e:
        raise H3TransportError(f"H3 request failed: {e}") from e


async def _h3_hit_async(
    addr: str,
    port: int,
    fields: list[tuple[bytes, bytes]],
    body: bytes,
    timeout: float,
) -> H3Reply:
    import ssl

    from aioquic.asyncio import connect
    from aioquic.asyncio.protocol import QuicConnectionProtocol
    from aioquic.h3.connection import H3Connection
    from aioquic.h3.events import DataReceived, HeadersReceived
    from aioquic.quic.configuration import QuicConfiguration

    config = QuicConfiguration(is_client=True, alpn_protocols=["h3"])
    config.verify_mode = ssl.CERT_NONE

    collected: dict = {
        "headers": None,
        "body": bytearray(),
        "done": asyncio.Event(),
        "http": None,
    }

    class _Client(QuicConnectionProtocol):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            collected["http"] = H3Connection(self._quic)

        def quic_event_received(self, event):
            for http_event in collected["http"].handle_event(event):
                if isinstance(http_event, HeadersReceived):
                    collected["headers"] = http_event.headers
                    if http_event.stream_ended:
                        collected["done"].set()
                elif isinstance(http_event, DataReceived):
                    collected["body"].extend(http_event.data)
                    if http_event.stream_ended:
                        collected["done"].set()

    async with connect(
        addr, port, configuration=config, create_protocol=_Client
    ) as client:
        http = collected["http"]
        stream_id = client._quic.get_next_available_stream_id()
        http.send_headers(stream_id=stream_id, headers=fields, end_stream=(body == b""))
        if body:
            http.send_data(stream_id=stream_id, data=body, end_stream=True)
        client.transmit()
        try:
            await asyncio.wait_for(collected["done"].wait(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise H3TransportError("H3 request timed out") from e

    return H3Reply.from_fields(collected["headers"] or [], bytes(collected["body"]))
