#!/usr/bin/env bash
# Installs (or updates) a SEPARATE copy of Vedetta on Home Assistant OS, for debugging: "Vedetta (debug)", slug local_vedetta_debug.
# The copy on the host is replaced as a whole (a file removed in the repository must not stay there: the front-end parts are joined
# by name, a stale part would be served too). It does not touch the real app: own data (/data), own port (8766), no MQTT (nothing is published to Home Assistant),
# no start at boot, no update from GitHub. Usage: VEDETTA_HA_HOST=<HA address> VEDETTA_HA_KEY=<ssh key> tools/deploy_debug.sh
set -euo pipefail
HOST="${VEDETTA_HA_HOST:?set VEDETTA_HA_HOST}"
KEY="${VEDETTA_HA_KEY:-$HOME/.ssh/id_ed25519}"
SLUG=vedetta_debug
cd "$(dirname "$0")/.."
python tools/run_tests.py
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r vedetta "$STAGE/$SLUG"
find "$STAGE/$SLUG" -name __pycache__ -prune -exec rm -rf {} +
sed -i \
  -e 's/^name: Vedetta$/name: Vedetta (debug)/' \
  -e "s/^slug: vedetta$/slug: $SLUG/" \
  -e 's/^version: "\(.*\)"$/version: "\1-debug"/' \
  -e 's/^boot: auto$/boot: manual/' \
  -e 's/\[PORT:8765\]/[PORT:8766]/' \
  -e 's/^ingress_port: 8765$/ingress_port: 8766/' \
  -e 's/^panel_icon: .*/panel_icon: mdi:bug/' \
  -e 's/^panel_title: .*/panel_title: Vedetta debug/' \
  -e '/^services:$/,/^  - mqtt:want$/d' \
  "$STAGE/$SLUG/config.yaml"
# The debug copy shows the one-time star invitation at once and again after every restart (to try it): no age needed, memory erased at start.
sed -i -e '/^set -e$/a export VEDETTA_STAR_MIN_AGE_DAYS=0' -e '/^set -e$/a rm -f /data/star_hint.json' -e '/^set -e$/a export VEDETTA_ARP_BLOCKS=1' "$STAGE/$SLUG/run.sh"
tar czf - -C "$STAGE" "$SLUG" | ssh -i "$KEY" "root@$HOST" \
  "rm -rf /local_apps/$SLUG && tar xzf - -C /local_apps && ha store reload && if ha apps info local_$SLUG 2>&1 | grep -q '^version: null'; then ha apps install local_$SLUG; else INFO=\$(ha apps info local_$SLUG 2>&1); if [ \"\$(echo \"\$INFO\" | sed -n 's/^version: //p')\" != \"\$(echo \"\$INFO\" | sed -n 's/^version_latest: //p')\" ]; then ha apps update local_$SLUG; else ha apps rebuild local_$SLUG; fi; fi && ha apps start local_$SLUG"
echo "Sent: the first build may take a few minutes. Then: Settings > Apps > Vedetta (debug) > Show in sidebar."
