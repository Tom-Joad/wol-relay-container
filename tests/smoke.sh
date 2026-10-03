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

echo "== PUID 0 is refused"
docker run -d --name "$NAME" "${HARDENING[@]}" -e PUID=0 -e WOL_AUTH_TOKEN=x "$IMAGE" >/dev/null
wait_for_exit || fail "kept running with PUID=0"
in_log 'refusing to run the relay as root' || fail "no message about PUID=0"
docker rm -f "$NAME" >/dev/null

echo "== start"
docker run -d --name "$NAME" "${HARDENING[@]}" -e PUID="$PUID" -e PGID="$PGID" \
    -e WOL_AUTH_TOKEN="$TOKEN" "$IMAGE" >/dev/null
for _ in $(seq 1 60); do
    [[ $(docker inspect -f '{{.State.Health.Status}}' "$NAME") == healthy ]] && break
    sleep 2
done
[[ $(docker inspect -f '{{.State.Health.Status}}' "$NAME") == healthy ]] || fail "not healthy"
in_log '"event":"starting"' || fail "no starting line"

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

if in_log "$TOKEN"; then fail "the token is in the log"; fi

echo "OK"
