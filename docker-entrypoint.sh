#!/bin/sh
# Make the bind-mounted /data directory usable, then drop root privileges.
set -e

DATA_DIR="${CURLBOOK_DATA_DIR:-/data}"
APP_USER=curlbook

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown "$APP_USER:$APP_USER" "$DATA_DIR" 2>/dev/null || true
    [ -f "$DATA_DIR/store.json" ] && chown "$APP_USER:$APP_USER" "$DATA_DIR/store.json" 2>/dev/null || true
    [ -d "$DATA_DIR/history" ] && chown -R "$APP_USER:$APP_USER" "$DATA_DIR/history" 2>/dev/null || true

    if setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups test -w "$DATA_DIR"; then
        exec setpriv --reuid="$APP_USER" --regid="$APP_USER" --init-groups "$@"
    fi
    echo "WARNING: $DATA_DIR is not writable by '$APP_USER'; running as root." >&2
fi

exec "$@"
