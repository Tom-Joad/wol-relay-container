#!/usr/bin/env bash
# Smoke test of the image, run with the same hardening as docker-compose.yml
# (read-only root, all capabilities dropped but SETUID/SETGID, no new
# privileges): settings check, the PUID/PGID drop, health, and the /wol
# endpoint sending a packet. Usage: tests/smoke.sh <image>
set -euo pipefail

IMAGE=${1:?usage: smoke.sh <image>}
NAME=wol-smoke-$$
TOKEN=smoke-test-token-$$
PUID=$(id -u); PGID=$(id -g)
[[ $PUID != 0 ]] || { PUID=1000; PGID=1000; }
HARDENING=(--read-only --cap-drop ALL --cap-add SETUID --cap-add SETGID
           --security-opt no-new-privileges)

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; docker logs "$NAME" >&2 2>&1 || true; exit 1; }

# Read the whole log first: with pipefail, `docker logs | grep -q` fails at
# random when grep exits early and docker logs gets SIGPIPE.
in_log() { local out; out=$(docker logs "$NAME" 2>&1); grep -qE -- "$1" <<<"$out"; }

wait_for_exit() {
    for _ in $(seq 1 30); do
        [[ $(docker inspect -f '{{.State.Status}}' "$NAME") == running ]] || return 0
        sleep 1
    done
    return 1
}

wait_healthy() {
    for _ in $(seq 1 60); do
        [[ $(docker inspect -f '{{.State.Health.Status}}' "$NAME") == healthy ]] && return 0
        sleep 2
    done
    return 1
}

# An HTTP request from inside the container; prints the status code.
request() { # method path [token] [json body]
    docker exec -i "$NAME" python - "$@" <<'PY'
import os, sys, urllib.error, urllib.request
method, path = sys.argv[1], sys.argv[2]
token = sys.argv[3] if len(sys.argv) > 3 else ""
body = sys.argv[4].encode() if len(sys.argv) > 4 else None
req = urllib.request.Request(
    f"http://127.0.0.1:{os.environ['WOL_LISTEN_PORT']}{path}", data=body, method=method,
    headers={"Content-Type": "application/json", **({"X-Auth-Token": token} if token else {})})
try:
    print(urllib.request.urlopen(req, timeout=5).status)
except urllib.error.HTTPError as exc:
    print(exc.code)
PY
}

echo "== without WOL_AUTH_TOKEN the container stops"
docker run -d --name "$NAME" "${HARDENING[@]}" "$IMAGE" >/dev/null
wait_for_exit || fail "kept running without WOL_AUTH_TOKEN"
in_log 'WOL_AUTH_TOKEN is required' || fail "no message about WOL_AUTH_TOKEN"
docker rm -f "$NAME" >/dev/null

echo "== a bad WOL_LOG_LEVEL stops the container with config_invalid"
docker run -d --name "$NAME" "${HARDENING[@]}" -e WOL_AUTH_TOKEN="$TOKEN" -e WOL_LOG_LEVEL=LOUD "$IMAGE" >/dev/null
wait_for_exit || fail "kept running with WOL_LOG_LEVEL=LOUD"
in_log '"event":"config_invalid".*WOL_LOG_LEVEL' || fail "no config_invalid line about WOL_LOG_LEVEL"
docker rm -f "$NAME" >/dev/null

echo "== a bad WOL_AUTH_TOKEN stops the container with config_invalid"
for bad in "x" "$TOKEN " "töken-0123456789abc"; do
    docker run -d --name "$NAME" "${HARDENING[@]}" -e WOL_AUTH_TOKEN="$bad" "$IMAGE" >/dev/null
    wait_for_exit || fail "kept running with WOL_AUTH_TOKEN='$bad'"
    in_log '"event":"config_invalid".*WOL_AUTH_TOKEN' || fail "no config_invalid line for WOL_AUTH_TOKEN='$bad'"
    docker rm -f "$NAME" >/dev/null
done

echo "== a bad WOL_LISTEN_HOST stops the container with config_invalid"
docker run -d --name "$NAME" "${HARDENING[@]}" -e WOL_AUTH_TOKEN="$TOKEN" -e WOL_LISTEN_HOST=192.168.1.300 "$IMAGE" >/dev/null
wait_for_exit || fail "kept running with WOL_LISTEN_HOST=192.168.1.300"
in_log '"event":"config_invalid".*WOL_LISTEN_HOST' || fail "no config_invalid line about WOL_LISTEN_HOST"
if in_log Traceback; then fail "a traceback instead of config_invalid"; fi
docker rm -f "$NAME" >/dev/null

echo "== the health check follows WOL_LISTEN_HOST and survives empty settings"
# 127.0.0.2: a specific address nothing answers on at 127.0.0.1. Empty values
# fall back to the defaults, and the health check must do the same.
for settings in "WOL_LISTEN_HOST=127.0.0.2" "WOL_LISTEN_HOST=" "WOL_LISTEN_PORT=" "WOL_LISTEN_PORT=8123"; do
    docker run -d --name "$NAME" "${HARDENING[@]}" -e WOL_AUTH_TOKEN="$TOKEN" -e "$settings" "$IMAGE" >/dev/null
    wait_healthy || fail "not healthy with $settings"
    docker rm -f "$NAME" >/dev/null
done

# 0, and the zero-padded spellings su-exec also reads as root.
for ids in "PUID=0" "PUID=00" "PGID=000"; do
    echo "== $ids is refused"
    docker run -d --name "$NAME" "${HARDENING[@]}" -e "$ids" -e WOL_AUTH_TOKEN="$TOKEN" "$IMAGE" >/dev/null
    wait_for_exit || fail "kept running with $ids"
    in_log 'refusing to run the relay as root' || fail "no message about $ids"
    docker rm -f "$NAME" >/dev/null
done

echo "== start"
docker run -d --name "$NAME" "${HARDENING[@]}" -e PUID="$PUID" -e PGID="$PGID" \
    -e WOL_AUTH_TOKEN="$TOKEN" "$IMAGE" >/dev/null
wait_healthy || fail "not healthy"
in_log '"event":"starting","version":"[0-9]+\.[0-9]+\.[0-9]+"' || fail "no starting line with the version"

USERS=$(docker exec "$NAME" ps -o user,args | awk '/app.py/ && !/awk/ {print $1}')
[[ -n $USERS ]] || fail "relay not running"
[[ $USERS != root && $USERS != 0 ]] || fail "relay runs as root"
[[ $USERS == "$PUID" || $(docker exec "$NAME" id -u "$USERS" 2>/dev/null) == "$PUID" ]] \
    || fail "relay doesn't run as PUID ($USERS)"

echo "== endpoints"
[[ $(request GET /health) == 200 ]] || fail "/health doesn't answer 200"
[[ $(request POST /wol) == 401 ]] || fail "/wol without token isn't 401"
[[ $(request POST /wol "$TOKEN" '{"mac":"not-a-mac"}') == 400 ]] || fail "invalid MAC isn't 400"
[[ $(request POST /wol "$TOKEN" '{"mac":"00:11:22:33:44:55"}') == 200 ]] || fail "valid request isn't 200"
in_log '"event":"packet_sent"' || fail "no packet_sent in the log"
[[ $(request POST /wol "$TOKEN" '{"mac":"11:22:33:44:55:66"') == 400 ]] || fail "truncated JSON isn't 400"
BIG=$(head -c 100000 /dev/zero | tr '\0' x)
[[ $(request POST /wol "" "$BIG") == 413 ]] || fail "a large body without token isn't 413"
in_log '"level":"ERROR"' && fail "an ERROR line in the log"
in_log '"event":"auth_rejected".*"client":' || fail "auth_rejected doesn't name the client"

if in_log "$TOKEN"; then fail "the token is in the log"; fi

echo "OK"
