#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
# The container of Vedetta as a person would run it (docker-compose.yml of the repository, image built here), checked from the outside:
# login everywhere, /healthz closed to the network, the one-time code in docker logs, setup, session, CSRF, logout, wrong attempts,
# the Linux capabilities of the process (only NET_RAW and NET_BIND_SERVICE), no secret in docker inspect, nmap and arp-scan installed.
# Usage (CI, Linux with Docker Engine): sh tools/ci/docker_smoke.sh <image>
set -eu
IMAGE="${1:-vedetta:ci}"
WORK="$(mktemp -d)"
LAN_IP="$(hostname -I | awk '{print $1}')"
H="http://${LAN_IP}:8765"
JAR="$WORK/cookies"
fail=0
ok() { printf 'ok: %s\n' "$1"; }
bad() { printf 'FAILED: %s\n' "$1"; fail=$((fail + 1)); }
expect() { if [ "$2" = "$3" ]; then ok "$1 ($3)"; else bad "$1: expected $2, got $3"; fi; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

sed -e "s#image: ghcr.io/sived80/vedetta:[0-9.]*#image: ${IMAGE}#" \
    -e "s#^\( *\)VEDETTA_HA_URL: .*#\1VEDETTA_HA_URL: http://192.0.2.10:8123#" docker-compose.yml > "$WORK/docker-compose.yml"
printf 'ci-placeholder-token-value\n' > "$WORK/ha_token.txt"
chmod 600 "$WORK/ha_token.txt"
cd "$WORK"
docker compose up -d
trap 'docker compose logs --no-color > "$WORK/container.log" 2>&1 || true; docker compose down -t 5 > /dev/null 2>&1 || true' EXIT

for i in $(seq 1 60); do
    if docker exec vedetta curl -fs -o /dev/null http://127.0.0.1:8765/healthz 2>/dev/null; then break; fi
    sleep 2
done
expect "the service answers inside the container" 200 "$(docker exec vedetta curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/healthz)"

SETUP="$(docker logs vedetta 2>&1 | grep -o 'One-time code, valid 60 minutes: [A-Z0-9-]*' | tail -1 | awk '{print $NF}')"
if [ -n "$SETUP" ]; then ok "the one-time code is in docker logs"; else bad "no one-time code in docker logs"; fi

expect "no session: the page leads to the setup" "303 ${H}/setup" "$(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' "$H/ha")"
expect "no session: the API is closed" 401 "$(code "$H/api/ha/devices")"
expect "no session: the event stream is closed" 401 "$(code "$H/api/ha/events")"
expect "no session: the files of the page are closed" 401 "$(code "$H/static/ha/boot.js")"
expect "/healthz is closed to the network" 404 "$(code "$H/healthz")"
expect "a setup without origin is refused" 403 "$(code -X POST -d "code=$SETUP" "$H/setup")"
PW="a long passphrase for the ci run"
expect "a wrong code sets nothing" 401 "$(code -H "Origin: $H" --data-urlencode "code=AAAA-BBBB-CCCC" --data-urlencode "password=$PW" --data-urlencode "confirm=$PW" "$H/setup")"
expect "the right code sets the password" 303 "$(code -c "$JAR" -H "Origin: $H" --data-urlencode "code=$SETUP" --data-urlencode "password=$PW" --data-urlencode "confirm=$PW" "$H/setup")"
if grep -q 'HttpOnly.*vedetta_session\|vedetta_session' "$JAR" && grep -q '#HttpOnly_' "$JAR"; then ok "the session cookie is HttpOnly"; else bad "the session cookie is not HttpOnly"; fi
expect "the setup page is gone" 404 "$(code "$H/setup")"
expect "with the session the page opens" 200 "$(code -b "$JAR" "$H/ha")"
expect "with the session the API answers" 200 "$(code -b "$JAR" "$H/api/ha/summary")"
expect "a change without the page header is refused" 403 "$(code -b "$JAR" -X POST -H "Origin: $H" "$H/api/refresh")"
expect "a change from another site is refused" 403 "$(code -b "$JAR" -X POST -H "Origin: http://192.0.2.66" -H 'X-Vedetta-Request: 1' "$H/api/refresh")"
expect "a change from the page goes through" 200 "$(code -b "$JAR" -X POST -H "Origin: $H" -H 'X-Vedetta-Request: 1' "$H/api/refresh")"
HEADERS="$(curl -s -D - -o /dev/null -b "$JAR" "$H/api/ha/summary")"
echo "$HEADERS" | grep -qi '^content-security-policy:.*frame-ancestors' && ok "CSP with frame-ancestors" || bad "no CSP"
echo "$HEADERS" | grep -qi '^cache-control: no-store' && ok "the API is not cached" || bad "the API may be cached"
echo "$HEADERS" | grep -qi '^server:' && bad "the Server header names the software" || ok "no Server header"
expect "logout" 303 "$(code -b "$JAR" -X POST -H "Origin: $H" "$H/logout")"
expect "after the logout the session is closed" 401 "$(code -b "$JAR" "$H/api/ha/summary")"
for i in 1 2 3 4 5; do code -H "Origin: $H" --data-urlencode "password=wrong password $i" "$H/login" > /dev/null; done
expect "after five wrong passwords: wait" 429 "$(code -H "Origin: $H" --data-urlencode "password=wrong password 6" "$H/login")"

CAPS="$(docker exec vedetta sh -c 'grep CapEff /proc/1/status' | awk '{print $2}')"
expect "the process has only NET_RAW and NET_BIND_SERVICE" 0000000000002400 "$CAPS"
if docker inspect vedetta | grep -q 'ci-placeholder-token-value'; then bad "the token is visible in docker inspect"; else ok "no token in docker inspect"; fi
if docker logs vedetta 2>&1 | grep -q 'ci-placeholder-token-value\|a long passphrase'; then bad "a secret is in the log"; else ok "no secret in the log"; fi
docker exec vedetta sh -c 'command -v nmap > /dev/null && command -v arp-scan > /dev/null' && ok "nmap and arp-scan installed at start" || bad "nmap or arp-scan missing"
docker exec vedetta sh -c 'ls /data/auth.json > /dev/null && stat -c %a /data/auth.json' | grep -q '^600$' && ok "the password hash file is 0600" || bad "auth.json is not 0600"

if [ "$fail" -gt 0 ]; then
    echo "--- container log"; docker logs vedetta 2>&1 | tail -40
    echo "$fail FAILED"; exit 1
fi
echo "ALL OK"
