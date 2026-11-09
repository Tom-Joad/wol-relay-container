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

# An ID of zeros only ("0", "00", "000") is root too, so a string comparison
# with "0" isn't enough: su-exec reads 00 as uid 0.
for id in "$PUID" "$PGID"; do
    case "$id" in
        *[!0]*) ;;
        *)
            echo "refusing to run the relay as root: set PUID and PGID to a non-zero ID" >&2
            exit 1
            ;;
    esac
done

exec su-exec "$PUID:$PGID" "$@"
