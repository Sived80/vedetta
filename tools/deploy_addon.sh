#!/usr/bin/env bash
# Aggiorna l'app Vedetta su Home Assistant OS copiando la cartella vedetta/ in /local_apps e ricostruendola.
# Uso: VEDETTA_HA_HOST=<indirizzo di HA> VEDETTA_HA_KEY=<chiave ssh> tools/deploy_addon.sh
# Serve il componente "Terminal & SSH" di HA con la chiave pubblica autorizzata (utente root).
set -euo pipefail
HOST="${VEDETTA_HA_HOST:?imposta VEDETTA_HA_HOST}"
KEY="${VEDETTA_HA_KEY:-$HOME/.ssh/id_ed25519}"
cd "$(dirname "$0")/.."
python tools/run_tests.py
tar czf - vedetta | ssh -i "$KEY" "root@$HOST" \
  "tar xzf - -C /local_apps && ha store reload && ha apps rebuild local_vedetta && ha apps start local_vedetta"
echo "Aggiornamento inviato: la ricostruzione puo' richiedere qualche minuto."
