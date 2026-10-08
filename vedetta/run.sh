#!/usr/bin/with-contenv bashio
# Starts Vedetta as a Home Assistant app: reads the options, works out the MQTT broker
# (manual options first, then the Home Assistant mqtt service) and runs a single uvicorn worker.
set -e

export VEDETTA_DATA_DIR=/data
export VEDETTA_PORT="$(bashio::addon.ingress_port)"
export VEDETTA_INGRESS_ONLY=1
export VEDETTA_LANGUAGE="$(bashio::config 'language')"
LOG_LEVEL="$(bashio::config 'log_level')"
export VEDETTA_LOG_LEVEL="${LOG_LEVEL}"
if bashio::config.has_value 'star_hint'; then
    export VEDETTA_STAR_HINT="$(bashio::config 'star_hint')"
fi

if bashio::config.has_value 'interface'; then
    export VEDETTA_IFACE="$(bashio::config 'interface')"
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

cd /app
bashio::log.info "Starting Vedetta on port ${VEDETTA_PORT}"
exec /opt/venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port "${VEDETTA_PORT}" --workers 1 --log-level "${LOG_LEVEL}"
