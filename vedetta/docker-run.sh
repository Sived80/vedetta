#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
# Starts Vedetta as a container of its own (Docker, for Home Assistant Container): the settings come from environment variables and
# secret files (DOCKER.md), the page has a login (app/access.py), the port is VEDETTA_PORT (8765). One uvicorn worker, as in the app.
set -eu

log() { printf '%s [docker-run] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

export VEDETTA_MODE=docker
export VEDETTA_DATA_DIR="${VEDETTA_DATA_DIR:-/data}"
export VEDETTA_PORT="${VEDETTA_PORT:-8765}"
LOG_LEVEL="$(printf '%s' "${VEDETTA_LOG_LEVEL:-info}" | tr 'A-Z' 'a-z')"
case "$LOG_LEVEL" in debug|info|warning|error) ;; *) LOG_LEVEL=info ;; esac
export VEDETTA_LOG_LEVEL="$LOG_LEVEL"
case "$VEDETTA_PORT" in ''|*[!0-9]*) log "VEDETTA_PORT must be a number (got '${VEDETTA_PORT}')"; exit 1 ;; esac

if ! mkdir -p "$VEDETTA_DATA_DIR" 2>/dev/null || ! [ -w "$VEDETTA_DATA_DIR" ]; then
    log "The data folder ${VEDETTA_DATA_DIR} is not writable: mount a volume there (see DOCKER.md)"
    exit 1
fi
chmod 700 "$VEDETTA_DATA_DIR" 2>/dev/null || true      # the map of the network, the password hash and the sessions: for the owner only

if [ -n "${VEDETTA_HA_URL:-}" ]; then
    # Only scheme, host and port: a user and a password written in the address by mistake never reach the log (the app refuses them).
    log "Home Assistant: $(printf '%s' "$VEDETTA_HA_URL" | sed -E 's#^([A-Za-z]+://)[^/@]*@#\1#; s#^([A-Za-z]+://[^/]*).*#\1#')"
else
    log "Home Assistant not configured (VEDETTA_HA_URL): Vedetta works on its own, without the data of Home Assistant"
fi

# The same self-watch as the app of Home Assistant: three /healthz in a row without an answer (a hung service) stop the container, and
# the restart policy of Compose (restart: unless-stopped) starts it again. /healthz answers only inside the container.
(
    sleep 180
    fails=0
    while sleep 60; do
        if curl -fs -m 10 "http://127.0.0.1:${VEDETTA_PORT}/healthz" > /dev/null; then fails=0; else fails=$((fails + 1)); fi
        if [ "${fails}" -ge 3 ]; then
            log "Vedetta does not answer: stopped, to be started again"
            kill "$$"
            exit 0
        fi
    done
) &

. /install-tools.sh log

cd /app
log "Starting Vedetta on port ${VEDETTA_PORT}"
# Behind a reverse proxy the scheme and the address of the client come from X-Forwarded-* only for the proxies listed in
# VEDETTA_TRUSTED_PROXIES (default: the host itself, 127.0.0.1); anyone else cannot pretend to be HTTPS or another address.
exec /opt/venv/bin/python -m uvicorn app.main:app \
    --host "${VEDETTA_BIND:-0.0.0.0}" --port "${VEDETTA_PORT}" --workers 1 --log-level "${LOG_LEVEL}" \
    --proxy-headers --forwarded-allow-ips "${VEDETTA_TRUSTED_PROXIES:-127.0.0.1}" --no-server-header
