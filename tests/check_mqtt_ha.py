"""Verifica della logica pura della pubblicazione MQTT (app/mqtt_ha.py), senza broker:
configurazione (ambiente > settings), slug, payload di discovery a dispositivo,
deduplica, rimozione, ripubblicazione dopo reset, password mai nelle API.
Con "python - < file" la cartella corrente deve essere la radice del progetto."""
import json
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app import mqtt_ha, settings

fails = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        fails.append(label)


# ---- configurazione ----
stored = {"mqtt_enabled": False, "mqtt_host": "", "mqtt_port": 1883, "mqtt_user": "", "mqtt_password": ""}
check(mqtt_ha.resolve_config(stored, {}) is None, "spento di default")
check(mqtt_ha.resolve_config({**stored, "mqtt_host": "h"}, {}) is None, "host senza enabled = spento")
c = mqtt_ha.resolve_config({**stored, "mqtt_enabled": True, "mqtt_host": "h", "mqtt_port": 1884, "mqtt_user": "u", "mqtt_password": "p"}, {})
check(c and c["source"] == "settings" and c["port"] == 1884 and c["user"] == "u", "attivo da settings")
c = mqtt_ha.resolve_config({**stored, "mqtt_enabled": True, "mqtt_host": "h", "mqtt_user": "u", "mqtt_password": "p"},
                           {"VEDETTA_MQTT_HOST": "core-mosquitto", "VEDETTA_MQTT_USER": "x", "VEDETTA_MQTT_PORT": "abc"})
check(c["source"] == "env" and c["host"] == "core-mosquitto" and c["user"] == "x" and c["port"] == 1883 and c["password"] == "p",
      "ambiente prevale campo per campo, porta non valida = 1883")
check(mqtt_ha.resolve_config(stored, {"VEDETTA_MQTT_HOST": "h"}) is not None, "solo ambiente host = attivo")

# ---- settings: validazione e password ----
tmp = Path(tempfile.mkdtemp())
settings.SETTINGS_PATH = tmp / "settings.json"
u = settings.mqtt_update({"mqtt_enabled": True, "mqtt_host": "broker.local", "mqtt_port": 1884,
                     "mqtt_user": "u", "mqtt_password": "segreta"})
check("mqtt_password" not in u and u["mqtt_password_set"] and settings.mqtt_load()["mqtt_password"] == "segreta", "password salvata ma non restituita")
check("mqtt_password" not in settings.load() and "mqtt_host" not in settings.load(), "load() delle impostazioni semplici invariato")
for bad in ({"mqtt_port": 0}, {"mqtt_port": "1883"}, {"mqtt_port": True}, {"mqtt_host": "a b"}, {"mqtt_enabled": 1}, {"mqtt_user": 5}):
    try:
        settings.mqtt_update(bad)
        check(False, f"rifiuta {bad}")
    except ValueError:
        check(True, f"rifiuta {bad}")
check(settings.mqtt_load()["mqtt_port"] == 1884, "i valori rifiutati non cambiano nulla")
settings.update({"poll_interval": 60}); settings.flows_update({"deep": ["ports_all"]})
check(settings.mqtt_load()["mqtt_password"] == "segreta", "altre modifiche non perdono la password")

# ---- slug ----
check(mqtt_ha.slug("shelly-1") == "shelly-1", "slug invariato se gia' pulito")
a, b = mqtt_ha.slug("scan.1"), mqtt_ha.slug("scan_1")
check(a != b and a.startswith("scan_1_"), "slug: id diversi non collidono")

# ---- discovery e deduplica ----
DEVS = {
    "d1": {"id": "d1", "name": "Presa", "ip": "10.0.0.2", "mac": "AA:BB:CC:00:00:01", "online": True,
           "brand": "Shelly", "latency_ms": 12, "is_mobile": False, "last_seen": None},
    "d2": {"id": "d2", "name": "Telefono", "ip": "10.0.0.3", "mac": None, "online": False,
           "vendor": "Apple", "latency_ms": None, "is_mobile": True, "last_seen": 1700000000.0},
}
KINDS = {"d1": "switch", "d2": "phone"}
seen: set = set()
want = mqtt_ha.build_desired(DEVS, KINDS, 2, seen)
t1 = mqtt_ha.device_topics("d1")
cfg1 = json.loads(want[t1["config"]])
check(t1["config"] == "homeassistant/device/vedetta_d1/config", "topic config dispositivo")
check("connections" not in cfg1["dev"] and cfg1["dev"]["via_device"] == "vedetta_hub"
      and cfg1["dev"]["manufacturer"] == "Shelly" and cfg1["dev"]["model"] == "switch",
      "device: sotto-dispositivo di Vedetta, mai agganciato al dispositivo vero per MAC")
check(set(cfg1["cmps"]) == {"tracker", "connectivity", "latency"}, "d1: tracker, connettivita', latenza")
check(cfg1["cmps"]["tracker"]["source_type"] == "router" and cfg1["cmps"]["tracker"]["p"] == "device_tracker", "tracker router")
uids = [c["unique_id"] for c in cfg1["cmps"].values()]
check(len(set(uids)) == 3 and all(u.startswith("vedetta_d1_") for u in uids), "unique_id stabili e distinti")
cfg2 = json.loads(want[mqtt_ha.device_topics("d2")["config"]])
check(set(cfg2["cmps"]) == {"tracker", "connectivity"} and "connections" not in cfg2["dev"], "d2: niente latenza ne' mac se ignoti")
check(want[t1["state"]] == "home" and want[mqtt_ha.device_topics("d2")["state"]] == "not_home", "home / not_home")
check(json.loads(want[mqtt_ha.device_topics("d2")["attrs"]])["last_seen"] is not None, "offline: ultimo visto")
# condivisione: si pubblica solo cio' che l'utente ha scelto; i contatori contano comunque tutti
only = mqtt_ha.build_desired(DEVS, KINDS, 2, set(), {"d1"})
check(mqtt_ha.device_topics("d1")["config"] in only and mqtt_ha.device_topics("d2")["config"] not in only, "solo i condivisi")
check(json.loads(only["vedetta/hub/state"])["offline"] == 1, "contatori su tutti i dispositivi")
none_shared = mqtt_ha.build_desired(DEVS, KINDS, 2, set(), set())
check(set(none_shared) == {"homeassistant/device/vedetta_hub/config", "vedetta/hub/state"}, "nessuno condiviso: solo Vedetta")
s = mqtt_ha.Sync()
s.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, set(), {"d1", "d2"}))
removed = {tp for tp, pl in s.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, set(), {"d1"})) if pl == ""}
check(mqtt_ha.device_topics("d2")["config"] in removed, "tolto dalla condivisione: sparisce da HA")
# messaggi retained di prima di un riavvio: se non servono piu', vengono cancellati
s2 = mqtt_ha.Sync()
old_cfg, old_state = mqtt_ha.device_topics("d2")["config"], mqtt_ha.device_topics("d2")["state"]
s2.adopt(old_cfg, "{}"); s2.adopt(old_state, "home")
gone = {tp for tp, pl in s2.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, set(), {"d1"})) if pl == ""}
check(gone == {old_cfg, old_state}, "retained vecchi non piu' condivisi: ripuliti")
hub = json.loads(want["vedetta/hub/state"])
check(hub == {"online": 1, "offline": 1, "mobile_online": 0, "new_devices": 2, "latency_avg": 12}, "contatori hub")
hcfg = json.loads(want["homeassistant/device/vedetta_hub/config"])
check(set(hcfg["cmps"]) == {"online", "offline", "mobile_online", "new_devices", "latency_avg", "scan"}
      and hcfg["cmps"]["scan"]["p"] == "button" and hcfg["cmps"]["scan"]["command_topic"] == mqtt_ha.SCAN_TOPIC, "hub: sensori e pulsante")
check(hcfg["availability_topic"] == "vedetta/status" and cfg1["availability_topic"] == "vedetta/status", "disponibilita' LWT")

sync = mqtt_ha.Sync()
first = sync.diff(want)
check(len(first) == len(want) and first[0][0].endswith("/config"), "primo invio: tutto, config per primi")
check(sync.diff(want) == [], "nessuna variazione = nessun messaggio")
DEVS["d1"]["latency_ms"] = 15
second = sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, seen))
topics = {m[0] for m in second}
check(topics == {t1["latency"], t1["attrs"], "vedetta/hub/state"}, "solo i topic variati: " + str(sorted(topics)))
DEVS["d1"]["latency_ms"] = None
third = dict(sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, seen)))
check(third.get(t1["latency"]) == "None" and t1["config"] not in third, "latenza persa: stato None, entita' resta")
sync.reset()
again = sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 2, seen))
check({m[0] for m in again} == set(mqtt_ha.build_desired(DEVS, KINDS, 2, seen)), "dopo reset si rimanda tutto")
# rimozione
del DEVS["d2"]
rem = sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 1, seen))
d2t = mqtt_ha.device_topics("d2")
removed = {t for t, p in rem if p == ""}
check(removed == set(d2t.values()) - {d2t["latency"]}, "dispositivo sparito: payload vuoto su config e stati")
check(sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 1, seen)) == [], "rimozione una volta sola")
# rimozione mentre scollegati: reset poi diff
sync.reset()
del DEVS["d1"]
rem2 = {t for t, p in sync.diff(mqtt_ha.build_desired(DEVS, KINDS, 0, seen)) if p == ""}
check(t1["config"] in rem2, "rimozione ricordata anche dopo reset")
check("d1" not in seen, "memoria latenza ripulita")

# ---- stato per le API senza password ----
mqtt_ha.service.cfg = None
st = mqtt_ha.service.status()
check("password" not in st and st["password_set"] is True and st["host"] == "broker.local", "status: niente password, solo password_set")
check("segreta" not in json.dumps(st) and "segreta" not in json.dumps(settings.mqtt_public()) + json.dumps(settings.load()), "password mai restituita")

print("\nTutto ok." if not fails else f"\n{len(fails)} controlli falliti.")
sys.exit(1 if fails else 0)
