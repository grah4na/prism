#!/bin/bash

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
COMPOSE="$ROOT/config/compose.yml"

if [ "$#" -eq 0 ]; then
    set -- 'help'
fi

build_soil() {
    docker pull debian:trixie-slim
    docker build "./images/http-prism-soil" -t http-prism-soil
}

case "$1" in
    repl)
        uv run ./tools/repl.py
    ;;

    build_seq)
        build_soil
        for container in $([ "$#" -eq 1 ] && uv run python3 -c 'import yaml; print(*yaml.safe_load(open("./config/compose.yml"))["services"].keys())' || echo "${@:2}"); do
            docker compose -f "$COMPOSE" --project-directory "$ROOT" build "$container"
        done
    ;;

    build)
        build_soil
        docker compose -f "$COMPOSE" --project-directory "$ROOT" build "${@:2}"
    ;;

    start)
        build_soil
        docker compose -f "$COMPOSE" --project-directory "$ROOT" up "${@:2}"
    ;;

    stop)
        docker compose -f "$COMPOSE" --project-directory "$ROOT" down
    ;;

    probe_quirks)
        if uv run ./tools/probe_quirks.py > out.yml; then
            mv out.yml config/quirks.yml
        else
            rm out.yml
        fi
    ;;

    update)
        if uv run ./tools/update.py > out.yml; then
            mv out.yml config/compose.yml
        else
            rm out.yml
        fi
    ;;
    
    *)
        echo "Usage: $0 [repl | start *[container] | build *[container] | stop | update]"
    ;;
esac
