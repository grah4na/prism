"""Minimal HTTP/3 echo server backed by aioquic.

This is the reference H3 origin for Prism. It returns the same JSON trace
shape as the HTTP/1 echo servers, so a 200 body is a request trace and the
response-direction comparison skips it.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import DataReceived, HeadersReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import ProtocolNegotiated


class EchoProtocol(QuicConnectionProtocol):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._http: H3Connection | None = None
        self._requests: dict[int, dict] = {}

    def quic_event_received(self, event) -> None:
        if isinstance(event, ProtocolNegotiated):
            self._http = H3Connection(self._quic)
        if self._http is None:
            return
        for http_event in self._http.handle_event(event):
            self._http_event(http_event)

    def _http_event(self, event) -> None:
        if isinstance(event, HeadersReceived):
            req = self._requests.setdefault(
                event.stream_id, {"headers": event.headers, "body": bytearray()}
            )
            req["headers"] = event.headers
            if event.stream_ended:
                self._respond(event.stream_id)
        elif isinstance(event, DataReceived):
            req = self._requests.setdefault(
                event.stream_id, {"headers": [], "body": bytearray()}
            )
            req["body"].extend(event.data)
            if event.stream_ended:
                self._respond(event.stream_id)

    def _respond(self, stream_id: int) -> None:
        req = self._requests.pop(stream_id)
        headers = req["headers"]
        body = bytes(req["body"])
        method = b""
        uri = b""
        for k, v in headers:
            if k == b":method":
                method = v
            elif k == b":path":
                uri = v
        doc = {
            "headers": [
                [base64.b64encode(k).decode(), base64.b64encode(v).decode()]
                for k, v in headers
            ],
            "body": base64.b64encode(body).decode(),
            "version": base64.b64encode(b"3").decode(),
            "uri": base64.b64encode(uri).decode(),
            "method": base64.b64encode(method).decode(),
        }
        payload = json.dumps(doc).encode()
        self._http.send_headers(
            stream_id, [(b":status", b"200"), (b"content-type", b"application/json")]
        )
        self._http.send_data(stream_id, payload, end_stream=True)
        self.transmit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="::")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--certificate", required=True)
    parser.add_argument("--private-key", required=True)
    args = parser.parse_args()

    configuration = QuicConfiguration(is_client=False, alpn_protocols=["h3"])
    configuration.load_cert_chain(args.certificate, args.private_key)

    async def run() -> None:
        await serve(
            args.host,
            args.port,
            configuration=configuration,
            create_protocol=EchoProtocol,
        )
        await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
