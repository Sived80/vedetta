#!/usr/bin/env bash
# Updates the Vedetta app on Home Assistant OS by copying the vedetta/ folder into /local_apps and rebuilding it.
# Usage: VEDETTA_HA_HOST=<HA address> VEDETTA_HA_KEY=<ssh key> tools/deploy_addon.sh
# Requires HA's "Terminal & SSH" component with the public key authorized (root user).
set -euo pipefail
HOST="${VEDETTA_HA_HOST:?set VEDETTA_HA_HOST}"
KEY="${VEDETTA_HA_KEY:-$HOME/.ssh/id_ed25519}"
cd "$(dirname "$0")/.."
python tools/run_tests.py
tar czf - vedetta | ssh -i "$KEY" "root@$HOST" \
  "tar xzf - -C /local_apps && ha store reload && ha apps rebuild local_vedetta && ha apps start local_vedetta"
echo "Update sent: the rebuild may take a few minutes."
