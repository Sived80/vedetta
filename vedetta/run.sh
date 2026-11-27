#!/usr/bin/with-contenv bashio
# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
# Starts Vedetta as a Home Assistant app: reads the options, works out the MQTT broker
# (manual options first, then the Home Assistant mqtt service) and runs a single uvicorn worker.
set -e

export VEDETTA_DATA_DIR=/data
export VEDETTA_PORT="$(bashio::app.ingress_port)"
export VEDETTA_INGRESS_ONLY=1
LOG_LEVEL="$(bashio::config 'log_level')"
export VEDETTA_LOG_LEVEL="${LOG_LEVEL}"

if bashio::config.has_value 'interface'; then
    export VEDETTA_IFACE="$(bashio::config 'interface')"
fi

# The functions that reach the internet: all on unless the options say otherwise (app/external.py reads these).
export VEDETTA_INTERNET_PUBLIC_IP="$(bashio::config 'internet_public_ip')"
export VEDETTA_INTERNET_PATH="$(bashio::config 'internet_path')"
export VEDETTA_INTERNET_MAC_DB="$(bashio::config 'internet_mac_database')"
if bashio::config.has_value 'internet_path_target'; then
    export VEDETTA_INTERNET_PATH_TARGET="$(bashio::config 'internet_path_target')"
fi

# The hour of the nightly maintenance (app/maintenance.py reads it; empty = 03:00).
if bashio::config.has_value 'night_hour'; then
    export VEDETTA_NIGHT_HOUR="$(bashio::config 'night_hour')"
fi

# MQTT: manual options win over the service ones.
if bashio::config.has_value 'mqtt_host'; then
    export VEDETTA_MQTT_HOST="$(bashio::config 'mqtt_host')"
    export VEDETTA_MQTT_PORT="$(bashio::config 'mqtt_port')"
    export VEDETTA_MQTT_USER="$(bashio::config 'mqtt_username')"
    export VEDETTA_MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
    bashio::log.info "MQTT: manual broker ${VEDETTA_MQTT_HOST}"
elif bashio::services.available 'mqtt'; then
    export VEDETTA_MQTT_HOST="$(bashio::services mqtt 'host')"
    export VEDETTA_MQTT_PORT="$(bashio::services mqtt 'port')"
    export VEDETTA_MQTT_USER="$(bashio::services mqtt 'username')"
    export VEDETTA_MQTT_PASSWORD="$(bashio::services mqtt 'password')"
    bashio::log.info "MQTT: Home Assistant service ${VEDETTA_MQTT_HOST}"
else
    bashio::log.info "MQTT not configured: publishing to Home Assistant is off"
fi

# The Supervisor cannot watch a port it chose at random: the app is watched from here. Three /healthz in a row without an
# answer (a hung service) stop it, and the Supervisor starts it again when its watchdog is on. /healthz answers on localhost.
(
    sleep 180
    fails=0
    while sleep 60; do
        if curl -fs -m 10 "http://127.0.0.1:${VEDETTA_PORT}/healthz" > /dev/null; then fails=0; else fails=$((fails + 1)); fi
        if [ "${fails}" -ge 3 ]; then
            bashio::log.warning "Vedetta does not answer: stopped, to be started again"
            kill "$$"
            exit 0
        fi
    done
) &

# Nmap and arp-scan are not in the published image (their licences: THIRD_PARTY_NOTICES.md). Home Assistant installs them from Alpine Linux
# here, when the app starts the first time (and after an update, which makes a new container); a restart of the same container finds them.
# A failed install does not stop the app: it starts without them and the install is tried again every 10 minutes in the background.
tools_missing() { ! command -v nmap > /dev/null 2>&1 || ! command -v arp-scan > /dev/null 2>&1; }
install_tools() { apk add --no-cache --quiet nmap nmap-scripts arp-scan; }
if tools_missing; then
    bashio::log.info "Installing nmap and arp-scan from Alpine Linux"
    for try in 1 2 3; do
        if install_tools; then break; fi
        sleep 10
    done
    if tools_missing; then
        bashio::log.warning "nmap and arp-scan could not be installed (no internet?): Vedetta starts without them and tries again every 10 minutes"
        ( while sleep 600; do if install_tools; then bashio::log.info "nmap and arp-scan installed"; break; fi; done ) &
    fi
fi

cd /app
bashio::log.info "Starting Vedetta on port ${VEDETTA_PORT}"
exec /opt/venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port "${VEDETTA_PORT}" --workers 1 --log-level "${LOG_LEVEL}"
