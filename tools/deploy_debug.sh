#!/usr/bin/env bash
# Installs (or updates) a SEPARATE copy of Vedetta on Home Assistant OS, for debugging: "Vedetta (debug)", slug local_vedetta_debug.
# The copy on the host is replaced as a whole (a file removed in the repository must not stay there: the front-end parts are joined
# by name, a stale part would be served too). It does not touch the real app: own data (/data), own port (chosen by the Supervisor, like the real app), no MQTT (nothing is published to Home Assistant),
# no start at boot, no update from GitHub. Usage: VEDETTA_HA_HOST=<HA address> VEDETTA_HA_KEY=<ssh key> [SKIP_TESTS=1] tools/deploy_debug.sh
# Built on the host from the working copy (the "image" line of config.yaml is dropped), unless
# DEBUG_IMAGE_TAG=0.11.1-test: the copy downloads that image built by GitHub (.github/workflows/images.yml, by hand) instead of
# being built on the host, to try the signed images before a release uses them.
set -euo pipefail
HOST="${VEDETTA_HA_HOST:?set VEDETTA_HA_HOST}"
KEY="${VEDETTA_HA_KEY:-$HOME/.ssh/id_ed25519}"
SLUG=vedetta_debug
# Title of the panel in the Home Assistant bar (VEDETTA_DEBUG_TITLE="" tries an empty one).
PANEL_TITLE="${VEDETTA_DEBUG_TITLE-Vedetta debug}"
cd "$(dirname "$0")/.."
# the tests first (in parallel, a few minutes); SKIP_TESTS=1 when they have just passed on this very code
if [ "${SKIP_TESTS:-0}" != "1" ]; then python tools/run_tests.py; fi
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -r vedetta "$STAGE/$SLUG"
find "$STAGE/$SLUG" -name __pycache__ -prune -exec rm -rf {} +
sed -i \
  -e 's/^name: Vedetta$/name: Vedetta (debug)/' \
  -e "s/^slug: vedetta$/slug: $SLUG/" \
  -e 's/^version: "\(.*\)"$/version: "\1-debug"/' \
  -e 's/^boot: auto$/boot: manual/' \
  -e 's/^panel_icon: .*/panel_icon: mdi:bug/' \
  -e "s/^panel_title: .*/panel_title: \"$PANEL_TITLE\"/" \
  -e '/^services:$/,/^  - mqtt:want$/d' \
  -e '/^image:/d' \
  "$STAGE/$SLUG/config.yaml"
if [ -n "${DEBUG_IMAGE_TAG:-}" ]; then
  sed -i -e "s/^version: .*/version: \"$DEBUG_IMAGE_TAG\"/" -e '/^image:/d' -e "/^slug: /a image: ghcr.io/sived80/{arch}-vedetta" "$STAGE/$SLUG/config.yaml"
fi
# The debug copy shows the one-time star invitation by the same rule as the real app (after a couple of days of use, once).
sed -i -e '/^set -e$/a export VEDETTA_ARP_BLOCKS=1' "$STAGE/$SLUG/run.sh"
tar czf - -C "$STAGE" "$SLUG" | ssh -i "$KEY" "root@$HOST" \
  "rm -rf /local_apps/$SLUG && tar xzf - -C /local_apps && ha store reload && if ha apps info local_$SLUG 2>&1 | grep -q '^version: null'; then ha apps install local_$SLUG; else INFO=\$(ha apps info local_$SLUG 2>&1); if [ \"\$(echo \"\$INFO\" | sed -n 's/^version: //p')\" != \"\$(echo \"\$INFO\" | sed -n 's/^version_latest: //p')\" ]; then ha apps update local_$SLUG; else ha apps rebuild local_$SLUG; fi; fi && ha apps start local_$SLUG"
echo "Sent: the first build may take a few minutes. Then: Settings > Apps > Vedetta (debug) > Show in sidebar."
