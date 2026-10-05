"""Impostazioni dell'utente (config/settings.json):
"alerts" = mostrare gli avvisi (nuova porta aperta, nuovo dispositivo...);
"poll_interval" = secondi tra un controllo e il successivo (valori fissi).
Le chiavi sconosciute vengono ignorate: il file contiene solo quelle note."""
import json
import logging
import os
import tempfile

from . import flows

from .paths import DATA_DIR as CONFIG_DIR
SETTINGS_PATH = CONFIG_DIR / "settings.json"

logger = logging.getLogger("dashboard")

# Intervallo di controllo ammesso (secondi). Attenzione: con MISS_LIMIT (state.py)
# un dispositivo risulta offline dopo 3 controlli falliti, quindi il ritardo di
# rilevamento scala con l'intervallo (30 s -> ~90 s, 5 min -> ~15 min).
POLL_INTERVALS = (10, 15, 30, 60, 120, 300)

# Controlli falliti di fila prima di dichiarare offline un dispositivo (isteresi):
# piu' alto = meno falsi "offline" (telefoni che dormono), ma rilevamento piu' lento.
MISS_LIMITS = (1, 2, 3, 5, 10)

DEFAULTS: dict = {"alerts": True, "poll_interval": 30, "miss_limit": 3}

# Pubblicazione verso Home Assistant (mqtt_ha.py, spenta di default). Sono chiavi
# del file separate da DEFAULTS: non compaiono in load()/update() (quindi neppure
# in GET /api/settings) e la password non esce mai dalle funzioni mqtt_*.
MQTT_DEFAULTS: dict = {"mqtt_enabled": False, "mqtt_host": "", "mqtt_port": 1883, "mqtt_user": "", "mqtt_password": ""}


def valid_value(key: str, value) -> bool:
    """Tipo giusto (bool non vale come int) e, per l'intervallo, valore ammesso."""
    if key == "poll_interval":
        return type(value) is int and value in POLL_INTERVALS
    if key == "miss_limit":
        return type(value) is int and value in MISS_LIMITS
    return isinstance(value, type(DEFAULTS[key]))


def mqtt_valid(key: str, value) -> bool:
    if key == "mqtt_port":
        return type(value) is int and 1 <= value <= 65535
    if key == "mqtt_host":
        return isinstance(value, str) and len(value) <= 253 and not any(c.isspace() for c in value)
    if key in ("mqtt_user", "mqtt_password"):
        return isinstance(value, str) and len(value) <= 256
    return isinstance(value, type(MQTT_DEFAULTS[key]))


def load() -> dict:
    """Impostazioni correnti: i default, sovrascritti dai valori validi del file."""
    result = dict(DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if isinstance(data, dict):
        for key, default in DEFAULTS.items():
            if key in data and valid_value(key, data[key]):
                result[key] = data[key]
    return result


def _save(data: dict) -> None:
    """Scrittura atomica: file temporaneo nella stessa cartella + os.replace
    (come devices_config._save)."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=SETTINGS_PATH.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, SETTINGS_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _stored_flows() -> dict[str, list[str]]:
    """Profili dei flussi salvati nel file e validi (chiave "flows"). Un profilo
    assente o non valido (file modificato a mano) conta come "non configurato"."""
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    raw = data.get("flows") if isinstance(data, dict) else None
    stored: dict[str, list[str]] = {}
    if isinstance(raw, dict):
        for profile, ids in raw.items():
            try:
                stored[profile] = flows.validate_profile(profile, ids)
            except flows.FlowError:
                logger.warning("Flusso '%s' nelle impostazioni non valido, uso il default", profile)
    return stored


def _stored_mqtt() -> dict:
    """Chiavi mqtt_* valide presenti nel file (altrimenti i default)."""
    result = dict(MQTT_DEFAULTS)
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return result
    if isinstance(data, dict):
        for key in MQTT_DEFAULTS:
            if key in data and mqtt_valid(key, data[key]):
                result[key] = data[key]
    return result


def _save_all(data: dict, stored_flows: dict[str, list[str]], mqtt: dict | None = None) -> None:
    """Salva le impostazioni semplici piu' i flussi configurati (se ce ne sono)
    e le chiavi mqtt_* gia' presenti (mai perse da una modifica altrui)."""
    out = dict(data)
    mqtt = _stored_mqtt() if mqtt is None else mqtt
    out.update({k: v for k, v in mqtt.items() if v != MQTT_DEFAULTS[k]})
    if stored_flows:
        out["flows"] = stored_flows
    _save(out)


def update(changes: dict) -> dict:
    """Applica solo le chiavi note con il tipo giusto, salva, ritorna tutto.
    ValueError se una chiave nota ha un valore del tipo sbagliato."""
    current = load()
    for key, default in DEFAULTS.items():
        if key in changes:
            if not valid_value(key, changes[key]):
                raise ValueError(key)
            current[key] = changes[key]
    _save_all(current, _stored_flows())  # i flussi gia' configurati non si perdono
    return current


def alerts_enabled() -> bool:
    return bool(load()["alerts"])


def miss_limit() -> int:
    """Controlli falliti di fila per l'offline; riletto a ogni ciclo."""
    return int(load()["miss_limit"])


def poll_interval() -> int:
    """Secondi tra i controlli; riletto a ogni ciclo (il cambio vale subito)."""
    return int(load()["poll_interval"])


# ---- pubblicazione MQTT (chiavi mqtt_*, mai in load()/update()) ----
def mqtt_load() -> dict:
    """Configurazione MQTT salvata, PASSWORD INCLUSA: solo per uso interno
    (mqtt_ha); alle API va mqtt_public()."""
    return _stored_mqtt()


def mqtt_public() -> dict:
    """Come mqtt_load() ma senza password (con password_set)."""
    data = _stored_mqtt()
    password = data.pop("mqtt_password")
    data["mqtt_password_set"] = bool(password)
    return data


def mqtt_update(changes: dict) -> dict:
    """Applica solo le chiavi mqtt_* note con il tipo giusto (ValueError se
    sbagliato: in tal caso non si salva nulla), scrittura atomica."""
    current = _stored_mqtt()
    for key in MQTT_DEFAULTS:
        if key in changes:
            if not mqtt_valid(key, changes[key]):
                raise ValueError(key)
            current[key] = changes[key]
    _save_all(load(), _stored_flows(), mqtt=current)
    return mqtt_public()


# ---- flussi di ricerca (chiave "flows", mai in load()/update() delle impostazioni semplici) ----
def flows_load() -> dict[str, list[str]]:
    """Step attivi per profilo: il default per i profili mai configurati."""
    result = flows.default_flows()
    result.update(_stored_flows())
    return result


def flows_update(changes: dict) -> dict[str, list[str]]:
    """Valida (anche solo alcuni profili), salva, ritorna i flussi completi.
    flows.FlowError (ValueError) se qualcosa non e' valido: in tal caso non si
    salva nulla."""
    validated = flows.validate_flows(changes)
    stored = _stored_flows()
    stored.update(validated)
    _save_all(load(), stored)
    return flows_load()


def flows_reset() -> dict[str, list[str]]:
    """Ripristina i default (toglie la chiave "flows" dal file)."""
    _save_all(load(), {})
    return flows_load()
