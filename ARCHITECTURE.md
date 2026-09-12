# Architecture

How Prism moves raw bytes through servers and turns the results into comparisons.

```
                  +----------------+
                  | payload /      |
                  | h2frames /     |  raw bytes you control
                  | h3frames       |
                  +-------+--------+
                          |
                          v
                  +-------+--------+
                  | transduce      |  optional: rewrite through
                  | (proxies)      |  transducer proxies
                  +-------+--------+
                          |
            +-------------+-------------+
            |                           |
   +--------v---------+       +---------v--------+
   | fanout / h2fanout|       | rfanout /        |
   | h3fanout / uf    |       | h3fanout         |
   | (request view:   |       | (response view:  |
   |  what backend   |       |  status/headers/ |
   |  parsed)        |       |  body)           |
   +--------+---------+       +---------+--------+
            |                           |
   +--------v---------+       +---------v--------+
   | grid / cluster   |       | rgrid / rcluster |
   +------------------+       +------------------+
```

## Pipeline stages

1. **Build bytes** with `payload`, `h2frames`, or `h3frames`.
   `payload` takes quoted strings with `\r \n \xff` escapes; `h2frames` /
   `h3frames` assemble wire frames (QUIC varints handled for H3).
2. **Optionally rewrite** them with `transduce <proxy>...`.
   Each proxy receives the current bytes, returns what it would forward,
   and the shell prints the bytes after every hop.
3. **Fan out** the same bytes to many servers in parallel (`prism/nethelp.py`).
   - Request direction: `fanout` / `h2fanout` decode the echo backend's
     `200` trace into `Req`, non-`200` into `Resp` (`prism/hosts.py:Origin.parsed_hit`).
   - Response direction: `rfanout` / `h3fanout` parse raw replies into
     `Resp` envelopes (status, headers, body) without decoding traces.
   - Raw mode: `uf` / `utf` show reply bytes unparsed.
4. **Compare** with `grid` (pairwise matrix) or `cluster` (equivalence groups).
   Both end the pipeline. See `prism/table.py` + `prism/scoring.py`.

Pipelines chain stages with `|`, multiple pipelines with `;`.
Bare `payload` prints the current bytes. See `prism/shell.py` for dispatch.

## Request vs response direction

- Request direction (`fanout | grid` / `cluster`) answers:
  *did backends parse the same request?* Compares method, URI, headers,
  body, version. Framing headers (`Content-Length`, `Transfer-Encoding`)
  are ignored — see `Req.comparable_headers` in `prism/models.py`.
- Response direction (`rfanout | rgrid` / `rcluster`) answers:
  *did clients get the same status/headers/body?* Only status codes are
  compared for equality, with dates, `Server`, `ETag`, `Via`, etc. ignored —
  see `Resp` in `prism/models.py`.

## Components

- `prism/shell.py` — REPL, pipeline dispatch, H2/H3 frame DSL.
- `prism/hosts.py` — Docker discovery (`load_hosts`), `Origin` / `Proxy` / `H3Origin`.
  Merges `config/compose.yml` roles, `config/quirks.yml` quirks,
  and container IPs on the `http-prism_default` network.
- `prism/http_parse.py` — H1 parsing, chunked bodies, trace decoding.
- `prism/h2mini.py` — minimal H2 framing / scanning.
- `prism/h3mini.py`, `prism/quichelp.py`, `prism/qpack.py` — H3 frames, QUIC transport, QPACK.
- `prism/table.py`, `prism/scoring.py` — grids, clusters, verdicts.
- `prism/pretty.py` — colored output + `help` text.
- `prism/models.py` — `Req` / `Resp` comparison semantics.
- `config/` — `compose.yml` (54 services), `quirks.yml`, `external.yml`.
- `tools/` — original reference implementation (parity tests).
- `tests/` — `test_parity.py`, `test_response.py`, `test_h3.py`.

## Project layout

```
prism/            interactive shell + differential core
  shell.py        REPL, pipeline dispatch, h2/h3 DSL
  hosts.py        Docker discovery, Origin/Proxy/H3Origin
  http_parse.py   H1 parsing, chunked, traces
  h2mini.py       minimal H2 framing
  h3mini.py / quichelp.py / qpack.py  H3 / QUIC / QPACK
  table.py / scoring.py  grids, clusters, verdicts
  pretty.py       colored output + help text
  models.py       Req/Resp comparison semantics
config/           compose.yml, quirks.yml, external.yml
images/           Dockerfiles for origins / transducers
tools/            original reference implementation
tests/            parity + response + H3 tests
scripts/          prism.sh, prism-docker.sh helpers
```
