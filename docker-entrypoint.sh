#!/bin/sh
# Run the relay as PUID:PGID. Started as root, drops to those IDs; started as
# another user (docker run --user), runs as that user and ignores PUID/PGID.
set -eu

PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

case "$PUID$PGID" in
    ''|*[!0-9]*)
        echo "PUID and PGID must be numeric, got PUID='$PUID' PGID='$PGID'" >&2
        exit 1
        ;;
esac

# Leading zeros are dropped first: an ID of zeros only ("00", "000") is
# root too. su-exec keeps only the low 32 bits of an ID, so 4294967296 would
# be root as well; 4294967295 is (uid_t)-1, which setuid refuses. Up to ten
# digits fit the 64-bit arithmetic of the shell.
canonical_id() {
    id=${1#"${1%%[!0]*}"}
    if [ -z "$id" ] || [ "${#id}" -gt 10 ] || [ "$id" -gt 4294967294 ]; then
        echo "refusing to run the relay as root: set PUID and PGID to an ID between 1 and 4294967294, got '$1'" >&2
        exit 1
    fi
    echo "$id"
}
PUID=$(canonical_id "$PUID")
PGID=$(canonical_id "$PGID")

exec su-exec "$PUID:$PGID" "$@"
