# Prism

A differential HTTP testing tool. It sends the same raw bytes to many HTTP
servers and shows which ones parse, accept, or reject them the same way.

The Python package in `prism/` is a fresh implementation that produces output
compatible with HTTP Prism (GPL-3.0); `tools/` holds the original reference
implementation used by the parity tests.

## Requirements

- Python 3.13+
- Docker (for the server containers)
- `uv` (for running the shell and tests)

## Run

```bash
uv run python -m prism
```

At the `prism>` prompt, chain stages with `|`:

```
payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | fanout | grid
```

Type `help` for the command overview, or `help <command>` for usage.

## Commands

- `payload '<bytes>'` — start a pipeline with raw bytes.
- `h2frames` / `h3frames` — build raw HTTP/2 / HTTP/3 frame bytes.
- `fanout` / `h2fanout` / `h3fanout` — send bytes and show parsed replies.
- `unparsed_fanout` (`uf`) / `unparsed_transducer_fanout` (`utf`) — show raw replies.
- `transduce` — rewrite bytes through transducer proxies.
- `grid` / `cluster` — compare request-direction views.
- `rfanout` / `rgrid` / `rcluster` — compare reply-direction (status, headers, bodies).
- `help`, `examples`, `exit`.

## HTTP/3

HTTP/3 needs the optional `aioquic` dependency and an H3 origin:

```bash
docker compose -f config/compose.yml --project-directory . -p http-prism build h3echo
docker compose -f config/compose.yml --project-directory . -p http-prism up -d h3echo

uv run --with aioquic python -m prism
```

Then:

```
payload 'GET / HTTP/1.1\r\nHost: a\r\n\r\n' | h3fanout | rgrid
```

## Tests

No docker required:

```bash
uv run --with pytest python -m pytest tests/
```
