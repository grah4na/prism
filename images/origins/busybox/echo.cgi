#!/bin/sh
# PRISM echo tracer for busybox httpd (routed via echo-catchall.patch).
# Emits the JSON trace described in prism/http_parse.py:decode_trace:
# base64 headers/method/uri/version/body. Header names keep busybox's
# CGI underscores (recorded as a header-name-translation quirk).

esc() {
    printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

b64() {
    printf '%s' "$1" | base64 -w0
}

printf 'Content-type: application/json\r\n\r\n'
printf '{"headers":['
first=1
env | while IFS='=' read -r name value; do
    case "$name" in
        HTTP_*) hname=$(printf '%s' "$name" | cut -c6-) ;;
        CONTENT_TYPE|CONTENT_LENGTH)
            [ -n "$value" ] || continue
            hname="$name"
            ;;
        *) continue ;;
    esac
    if [ "$first" = 1 ]; then
        first=0
    else
        printf ','
    fi
    printf '["%s","%s"]' "$(b64 "$(esc "$hname")")" "$(b64 "$(esc "$value")")"
done
printf '],"body":"'
len=${CONTENT_LENGTH:-0}
case "$len" in
    ''|*[!0-9]*) ;;
    *) [ "$len" -gt 0 ] && head -c "$len" | base64 -w0 ;;
esac
printf '","version":"%s","uri":"%s","method":"%s"}' \
    "$(b64 "$(esc "${SERVER_PROTOCOL:-}")")" \
    "$(b64 "$(esc "${REQUEST_URI:-}")")" \
    "$(b64 "$(esc "${REQUEST_METHOD:-}")")"
