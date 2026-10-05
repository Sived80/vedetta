#!/usr/bin/with-contenv bashio
# Avvio di Vedetta come app di Home Assistant: legge le opzioni, ricava il broker MQTT
# (opzioni manuali prima, poi il servizio mqtt di HA) ed esegue un solo worker uvicorn.
set -e

export VEDETTA_DATA_DIR=/data
export VEDETTA_PORT="$(bashio::addon.ingress_port)"
export VEDETTA_INGRESS_ONLY=1
export VEDETTA_LANGUAGE="$(bashio::config 'language')"
LOG_LEVEL="$(bashio::config 'log_level')"
export VEDETTA_LOG_LEVEL="${LOG_LEVEL}"

if bashio::config.has_value 'interface'; then
    export VEDETTA_IFACE="$(bashio::config 'interface')"
fi

# MQTT: le opzioni manuali prevalgono su quelle del servizio.
if bashio::config.has_value 'mqtt_host'; then
    export VEDETTA_MQTT_HOST="$(bashio::config 'mqtt_host')"
    export VEDETTA_MQTT_PORT="$(bashio::config 'mqtt_port')"
    export VEDETTA_MQTT_USER="$(bashio::config 'mqtt_username')"
    export VEDETTA_MQTT_PASSWORD="$(bashio::config 'mqtt_password')"
    bashio::log.info "MQTT: broker manuale ${VEDETTA_MQTT_HOST}"
elif bashio::services.available 'mqtt'; then
    export VEDETTA_MQTT_HOST="$(bashio::services mqtt 'host')"
    export VEDETTA_MQTT_PORT="$(bashio::services mqtt 'port')"
    export VEDETTA_MQTT_USER="$(bashio::services mqtt 'username')"
    export VEDETTA_MQTT_PASSWORD="$(bashio::services mqtt 'password')"
    bashio::log.info "MQTT: servizio di HA ${VEDETTA_MQTT_HOST}"
else
    bashio::log.info "MQTT non configurato: pubblicazione verso HA disattivata"
fi

cd /app
bashio::log.info "Avvio Vedetta sulla porta ${VEDETTA_PORT}"
exec /opt/venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port "${VEDETTA_PORT}" --workers 1 --log-level "${LOG_LEVEL}"
