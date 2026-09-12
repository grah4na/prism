# Prism

<p>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/grah4na/prism?style=flat" alt="License"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-blue?style=flat&logo=python&logoColor=white" alt="Python 3.13+">
  <img src="https://img.shields.io/badge/docker-required-blue?style=flat&logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/uv-package_manager-purple?style=flat" alt="uv">
  <img src="https://img.shields.io/badge/HTTP-1.1%20%C2%B7%20H2%20%C2%B7%20H3-orange?style=flat" alt="HTTP/1.1, H2, H3">
  <img src="https://img.shields.io/badge/tests-pytest-green?style=flat&logo=pytest" alt="pytest">
</p>

Differential HTTP testing. Send the same raw bytes to many HTTP servers and see which ones parse, forward, accept, or reject them differently. Inspired by [http-garden](https://github.com/narfindustries/http-garden).

Prism is useful for finding parser differentials, request-smuggling primitives, transducer normalizations, and H1/H2/H3 edge cases , by comparing real servers side-by-side instead of reasoning about specs.

The interactive shell in `prism/` is a clean reimplementation with output compatible with [HTTP Prism](https://github.com/http-prism/http-prism). `tools/` holds the original reference implementation used by the parity tests.

## Features

- Raw-byte pipelines: `payload` → `fanout` → `grid` / `cluster`
- Request direction (what the backend saw) and response direction (status / headers / body)
- Transducer proxies: rewrite bytes through `squid`, `nginx_proxy`, `haproxy`, etc. with `transduce`
- HTTP/1.1, HTTP/2 (`h2frames` / `h2fanout`), and HTTP/3 over QUIC (`h3frames` / `h3fanout`)
- Pairwise difference matrix (`grid` / `rgrid`) and equivalence grouping (`cluster` / `rcluster`)
- Raw mode (`uf` / `utf`) for unparsed reply bytes
- 54 containerized servers: 39 origins, 14 transducers, 1 H3 origin (see `config/compose.yml`)
- Parity-tested against the reference implementation (`tests/test_parity.py`)

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- Docker (for the server containers)
- Optional: `aioquic` (only for HTTP/3)

## Quickstart

```bash
# 1. Build + start servers
docker compose -f config/compose.yml --project-directory . -p http-prism up -d --build

# or via helper script:
./scripts/prism-docker.sh start

# 2. Start the shell
uv run python -m prism
# or
./scripts/prism.sh
```

Then at the prompt:

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | fanout | grid
prism> help
prism> help fanout
prism> exit
```

Stop servers when done:

```bash
docker compose -f config/compose.yml --project-directory . -p http-prism down
./scripts/prism-docker.sh stop
```

> See [ARCHITECTURE.md](ARCHITECTURE.md) for pipeline flow and component details.

## Command reference

### Start a pipeline

| Command | Description |
| ------- | ----------- |
| `payload '<bytes>' [...]` | Start with raw bytes. `\r \n \xff` escapes supported. Bare `payload` prints current bytes. |
| `h2frames [pri] [frame ...]` | Build raw HTTP/2 wire bytes. Each frame: `[ type <t> flags { ... } id <n> payload '<bytes>' ]`. |
| `h3frames [frame ...]` | Build raw HTTP/3 frame bytes. Each frame: `[ type <t> payload '<bytes>' ]`. |

### Rewrite and send

| Command | Description | Default targets |
| ------- | ----------- | --------------- |
| `transduce <proxy> [...]` | Pipe bytes through transducer proxies, printing after each hop. | — (required) |
| `fanout [server ...]` | Send bytes, show parsed request/response views. | all origins |
| `h2fanout [server ...]` | Like `fanout`, only H2-capable origins. | H2 origins |
| `h3fanout [server ...]` | Send to H3 origins over QUIC, show decoded replies. | all H3 origins |
| `unparsed_fanout` / `uf [server ...]` | Send bytes, show raw reply bytes. | all origins |
| `unparsed_transducer_fanout` / `utf [proxy ...]` | Raw replies from proxies. | all proxies |
| `rfanout [server ...]` | Send bytes, show reply envelopes (status, headers, body). | all servers |

### Compare and view

| Command | Input | Description |
| ------- | ----- | ----------- |
| `grid [server ...]` | `fanout` | Pairwise request-view difference matrix. Ends pipeline. |
| `cluster [server ...]` | `fanout` | Group servers that parsed identically. Ends pipeline. |
| `rgrid [server ...]` | `rfanout` / `h3fanout` | Pairwise response-view difference matrix. Ends pipeline. |
| `rcluster [server ...]` | `rfanout` / `h3fanout` | Group servers that replied alike. Ends pipeline. |

### Session

| Command | Description |
| ------- | ----------- |
| `help [command]` | Overview, or usage + example for one command. |
| `help examples` | Copy-paste example pipelines. |
| `exit` / `quit` | Leave (Ctrl-D also works). |

In-shell help is authoritative:

```
prism> help fanout
prism> help h2frames
prism> help examples
```

## Examples

Basic differential — do all origins agree?

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | fanout | grid
```

Narrow to two servers, group instead of matrix:

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | fanout nginx apache_httpd | cluster
```

Smuggling-style probe with duplicate framing:

```
prism> payload 'POST / HTTP/1.1\r\nHost: a\r\nContent-Length: 5\r\nTransfer-Encoding: chunked\r\n\r\nhello' | fanout | grid
```

Missing `Host`, chunked body, absolute URI:

```
prism> payload 'GET / HTTP/1.1\r\n\r\n' | fanout | grid
prism> payload 'POST / HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n4\r\nWiki\r\n0\r\n\r\n' | fanout | grid
prism> payload 'GET http://a/ HTTP/1.1\r\nHost: a\r\n\r\n' | fanout | grid
```

Through a transducer:

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | transduce squid | fanout | grid
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | utf squid
```

Raw bytes, no parsing:

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | uf nginx
```

Response direction (compare what clients would see, not what backends parsed):

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | rfanout | rgrid
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | rfanout reactphp busybox | rcluster
```

HTTP/2:

```
prism> h2frames pri [ type settings flags { 0 } id 0 payload '' ] | h2fanout | grid
```

HTTP/3 (requires `aioquic`, see below):

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | h3fanout | rgrid
```

## Reading the output

`fanout` prints per-server parsed views:

```
nginx: [
    HTTPRequest(
        method=b'GET', uri=b'/', version=b'1.1',
        headers=[
            (b'host', b'a'),
        ],
        body=b'',
    ),
]
```

`grid` prints a pairwise matrix:

- `✓` (green): same interpretation
- `X` (red): discrepancy (different method / URI / headers / body / type)
- `X` (white-on-red): invalid (a server rejected what the other accepted)
- blank diagonal: self-comparison

`cluster` prints equivalence groups:

```
    0. nginx apache_httpd
    1. gunicorn hyper
```

Request direction (`fanout | grid/cluster`) answers: *did backends parse the same request?*
Response direction (`rfanout | rgrid/rcluster`) answers: *did clients get the same status/headers/body?*
Framing headers (`Content-Length`, `Transfer-Encoding`), dates, `Server`, `ETag`, etc. are ignored where they carry no protocol signal — see `prism/models.py`.

## Security vulnerabilities you can find

Every `X` in a grid is a parser disagreement, and parser disagreements are where HTTP-layer vulnerabilities live. Typical classes:

- **HTTP request smuggling** (`CL.CL`, `CL.TE`, `TE.CL`, `TE.TE`) — duplicate or conflicting framing headers, chunked edge cases (bad chunk sizes, extensions, bare `LF`, missing terminator). Probe with `payload ... | transduce <proxy> | fanout | grid`.
- **Request queue poisoning / desync** — one server sees one request where another sees two (or rejects what the other accepts — white-on-red `X`). Look for body-length and keep-alive disagreements.
- **Cache poisoning** — header or URI normalization differences (case, duplicates, whitespace, absolute URI) that make a cache and an origin disagree on the cache key vs the forwarded request.
- **ACL / access-control bypass** — URI interpretation differences (absolute URI, dot segments, prefix handling, method handling) between a transducer and an origin.
- **Transducer normalization bugs** — proxies that join, drop, rename, or reorder headers differently (`transduce` shows each hop; compare with `utf`).
- **Response-handling differences** — status/header/body disagreements via `rfanout | rgrid` (e.g. one server rejects with `400` while another processes the request).
- **H2 / H3 framing edge cases** — preface, settings, flags, and frame-type handling via `h2frames | h2fanout` and `h3fanout`.

Prism finds *candidates*, not exploits: confirm a discrepancy is reachable end-to-end (transducer → origin) and security-relevant before treating it as a vulnerability. See the [http-garden TROPHIES](https://github.com/narfindustries/http-garden/blob/main/TROPHIES.md) for examples of what this workflow has historically uncovered.

## HTTP/2

`h2frames` builds wire bytes. Frame types: `data headers priority rst_stream settings push_promise ping goaway window_update continuation` (or `0`–`255`).

```
prism> h2frames pri [ type settings flags { 0 } id 0 payload '' ] | h2fanout
```

Flags use `{ ... }` with names (`end_stream ack end_headers padded priority`) or bit numbers (`0`–`7`).

## HTTP/3

Requires the optional `aioquic` dependency and an H3 origin:

```bash
docker compose -f config/compose.yml --project-directory . -p http-prism build h3echo
docker compose -f config/compose.yml --project-directory . -p http-prism up -d h3echo

uv run --with aioquic python -m prism
```

Then:

```
prism> payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | h3fanout | rgrid
```

`h3frames` builds H3 frames (`data headers cancel_push settings push_promise goaway max_push_id`); QUIC varints are handled for you. `h3fanout` takes a plain H1 request line from `payload`, converts it to H3 pseudo-headers, and routes results through the response-direction views (`rgrid` / `rcluster`).

## Configuration

- `config/compose.yml` — 54 services with `x-props.role`: `origin`, `transducer`, `h3-origin`. Source of truth for server discovery.
- `config/quirks.yml` — per-server parser quirks (H2/0.9 support, header translation, whitelists, etc.).
- `config/external.yml` — optional externally-hosted servers (empty by default).
- `prism/hosts.py:load_hosts` — merges compose + quirks + Docker network IPs.

Probe quirks / regenerate compose with:

```bash
./scripts/prism-docker.sh probe_quirks
./scripts/prism-docker.sh update
./scripts/prism-docker.sh build [container...]
```

## Tests

No Docker required:

```bash
uv run --with pytest python -m pytest tests/
```

- `test_parity.py` — request/response parsing, scoring, grid rendering match `tools/`
- `test_response.py` — response-direction comparison
- `test_h3.py` — H3 frame codec and QPACK

Lint / types (dev group in `pyproject.toml`): `black`, `mypy`, `pylint`.

## References

- B. Jabiyev et al., [T-Reqs: HTTP Request Smuggling with Differential Fuzzing](https://doi.org/10.1145/3460120.3485384), ACM CCS 2021.
- B. Kallus et al., [The HTTP Garden: Discovering Parsing Vulnerabilities in HTTP/1.1 Implementations by Differential Fuzzing of Request Streams](https://arxiv.org/abs/2405.17737), 2024.

## License

Apache-2.0 — see `LICENSE`. Output format is kept compatible with the upstream HTTP Prism tool.
