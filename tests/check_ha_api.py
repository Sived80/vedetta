"""Verifica della logica pura della dashboard in stile Home Assistant (/ha):
tipo di dispositivo dedotto, formato compatto, riepilogo, registro eventi,
segmenti storici, traduzioni (chiavi usate da ha.js presenti in en e it).
Nel container: python tests/check_ha_api.py
In locale (Windows) funziona anche senza zoneinfo: se app.applog non si
importa lo si simula. Usa un database temporaneo.
Con "python - < file" la cartella corrente deve essere la radice del progetto."""
import json
import re
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    import logging
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app import ha_data, i18n
from app.history import History

ROOT = Path(".")


def dev(**kw):
    base = {
        "id": "d1", "name": "Dispositivo", "is_mobile": False, "ip": "10.0.0.5", "port": 80, "url": "http://10.0.0.5:80",
        "online": True, "uptime": 3600, "mac": "AA:BB:CC:00:00:01", "vendor": None, "signal_kind": None,
        "signal_value": None, "signal_band": None, "signal_label": None, "signal_color": None,
        "extra": {}, "scanned_ports": [], "scanned_at": None, "last_seen": None,
    }
    base.update(kw)
    return base


def port(n, label=None, cat="other"):
    return {"label": label or str(n), "confirmed": True, "category": cat}


# 1) tipo dedotto: regole generiche, nessun caso particolare
cases = [
    (dev(is_mobile=True, name="qualunque"), None, "phone"),
    (dev(name="Camera luce"), "shelly_gen1", "iot"),               # adapter shelly
    (dev(name="Plug cucina", vendor="Shelly"), None, "iot"),       # parola chiave
    (dev(name="Salotto", vendor="Philips Hue"), None, "iot"),
    (dev(name="HP", scanned_ports=[port(631, "631 · ipp")]), None, "printer"),
    (dev(name="Ufficio", vendor="Epson"), None, "printer"),
    (dev(name="Samsung TV salotto"), None, "media"),
    (dev(name="Bravia"), None, "media"),
    # NVR e telecamere: dati reali del test (RTSP aperto, ONVIF dichiarato); "webserver" non e' un server.
    (dev(name="192.168.50.190", vendor="Milesight", extra={"http_server": "webserver", "title": "Login"},
         scanned_ports=[port(80, "80 · http"), port(554, "554 · rtsp")]), None, "media"),
    (dev(name="192.168.50.199", extra={"onvif_name": "IPCAM", "rtsp_server": "Hipcam RealServer/V1.0"}), None, "media"),
    (dev(name="Cucina", vendor="Sonos"), None, "audio"),
    (dev(name="Gateway casa"), None, "router"),
    (dev(name="FRITZ!Box 7590"), None, "router"),
    (dev(name="Sensore balcone"), None, "iot"),
    (dev(name="x", vendor="Espressif"), None, "iot"),
    (dev(name="x", scanned_ports=[port(1883, "1883 · mqtt")]), None, "iot"),
    (dev(name="MacBook di Paola"), None, "pc"),
    (dev(name="x", scanned_ports=[port(3389, "3389 · rdp")]), None, "pc"),
    (dev(name="proxmox"), None, "server"),
    (dev(name="x", scanned_ports=[port(22, "22 · ssh"), port(8006, "8006 · https")]), None, "server"),
    (dev(name="x", extra={"os": "Linux 5.x"}), None, "generic"),   # Linux da solo non e' un ruolo (gira anche su telefoni, TV, router)
    (dev(name="x", vendor="Canonical Ltd"), None, "generic"),         # "canon" dentro "canonical": non e' una stampante
    (dev(name="Verbose logger"), None, "generic"),                    # "bose" dentro "verbose": non e' audio
    (dev(name="qualcosa"), None, "generic"),
]
for device, adapter, expected in cases:
    got = ha_data.infer_type(device, adapter)
    assert got == expected, (device["name"], adapter, expected, got)
assert set(c[2] for c in cases) <= set(ha_data.TYPE_ORDER)
print("ok: tipo dedotto (%d casi)" % len(cases))

# 2) formato compatto
i18n.use("en")
d = dev(
    name="Shelly 1", vendor="Shelly", signal_kind="wifi", signal_value=-58, signal_band="2.4 GHz", signal_label="good",
    signal_color="green", extra={"vendor": "Shelly", "model": "SHSW-1", "title": "Pagina"}, scanned_ports=[port(80, "80 · http", "web")],
    scanned_at=1000.0, online=False, last_seen=1234.5,
)
c = ha_data.compact_device(d, {"adapter": "shelly_gen1", "mobile": None})
keys = {"id", "name", "ip", "port", "mac", "vendor", "vendor_role", "brand", "brand_source", "brand_confidence", "brand_evidence", "brand_declared", "battery", "battery_source", "type", "icon", "is_mobile", "mobile_mode", "name_source", "wol_ok", "ha_share", "type_user", "brand_user", "online", "last_seen", "uptime",
        "signal", "latency_ms", "latency_color", "ports", "url", "title", "scanned_at", "attrs"}
assert set(c) == keys, set(c) ^ keys
assert c["type"] == "iot" and c["mobile_mode"] == "auto" and c["online"] is False and c["last_seen"] == 1234.5
assert c["signal"]["display"] == "-58 dBm · 2.4 GHz" and c["signal"]["text"] == "Good", c["signal"]
assert c["ports"] == [{"label": "80 · http", "category": "web", "confirmed": True}]
assert c["title"] == "Pagina" and [a["key"] for a in c["attrs"]] == ["model", "title"], c["attrs"]
assert ha_data.compact_device(dev(), {"mobile": True})["mobile_mode"] == "yes"
assert ha_data.compact_device(dev(), {"mobile": False})["mobile_mode"] == "no"
online = ha_data.compact_device(dev(last_seen=99.0))
assert online["last_seen"] is None, "da online last_seen non si espone"
assert ha_data.compact_device(dev(signal_kind="lan", signal_value="1000 Mbps"))["signal"]["display"] == "1000 Mbps"
assert ha_data.compact_device(dev())["signal"] is None
json.dumps(c)  # serializzabile
print("ok: formato compatto")

# 3) riepilogo
devices = [
    dev(id="a", ip="10.0.0.1", vendor="Allterco", brand="Shelly", online=True),
    dev(id="b", ip="10.0.0.2", vendor="Espressif", brand="Shelly", online=False, is_mobile=False),
    dev(id="c", ip="10.0.0.3", vendor="Apple", brand="Apple", online=True, is_mobile=True, name="iPhone"),
    dev(id="d", ip="10.0.0.4", vendor=None, online=False, is_mobile=True, name="Pixel"),
]
s = ha_data.build_summary(devices, {"interval_ms": 30000, "next_in_ms": 12000}, {"search": True, "rescanning": ["a"]},
                          {"count": 1, "devices": [{"mac": "AA"}]}, rev=7)
assert (s["total"], s["online"], s["offline"], s["mobile"], s["mobile_online"]) == (4, 2, 2, 2, 1), s
assert s["online_pct"] == 50.0 and s["rev"] == 7
assert s["brands"][0] == {"brand": "Shelly", "count": 2}
assert s["brands"][-1] == {"brand": None, "count": 1}, "senza marca in fondo"
assert s["poll"] == {"interval_ms": 30000, "next_in_ms": 12000, "paused": False, "paused_in_ms": None}
assert s["activity"] == {"search": True, "rescanning": ["a"]}
assert s["new_devices"]["count"] == 1
assert s["types"].get("phone") == 2
empty = ha_data.build_summary([], {}, {}, {}, 0)
assert empty["total"] == 0 and empty["online_pct"] is None and empty["brands"] == []
# la marca e' quella del PRODOTTO: un chip senza marca nota non conta come marca
chips = [
    dev(id="e", ip="10.0.0.5", vendor="Bouffalo Lab", brand=None, online=True),
    dev(id="f", ip="10.0.0.6", vendor="Bouffalo Lab", brand=None, online=True, battery="yes"),
    dev(id="g", ip="10.0.0.7", vendor="TP-Link", brand="TP-Link", online=True),
    dev(id="h", ip="10.0.0.8", vendor="TP-Link", brand=None, online=True),
]
s2 = ha_data.build_summary(chips, {}, {}, {}, 0)
assert s2["brands"] == [{"brand": None, "count": 3}, {"brand": "TP-Link", "count": 1}] or     s2["brands"] == [{"brand": "TP-Link", "count": 1}, {"brand": None, "count": 3}], s2["brands"]
assert s2["unknown_chips"] == [{"vendor": "Bouffalo Lab", "count": 2}, {"vendor": "TP-Link", "count": 1}], s2["unknown_chips"]
assert s2["battery"] == 1
print("ok: riepilogo")

# 4) registro eventi e storico (database temporaneo)
tmp = Path(tempfile.mkdtemp())
hist = History(tmp / "t.db")
now = time.time()
hist.record_presence("a", "10.0.0.1", "AA:BB:CC:00:00:01", True, now - 7200)
hist.record_presence("a", "10.0.0.1", None, False, now - 3600)
hist.record_presence("gone", "10.0.0.9", None, True, now - 1800)
rows = ha_data.recent_presence(10, hist)
assert [r["device_id"] for r in rows] == ["gone", "a", "a"], rows
assert rows[1]["online"] is False and rows[2]["online"] is True
assert len(ha_data.recent_presence(1, hist)) == 1
assert len(ha_data.recent_presence(0, hist)) == 1, "limite minimo 1"
entries = ha_data.logbook_entries(rows, {"a": dev(id="a", name="Luce corridoio")}, {})
assert entries[0]["name"] == "10.0.0.9" and entries[0]["known"] is False and entries[0]["type"] == "generic"
assert entries[1]["name"] == "Luce corridoio" and entries[1]["message"] == "went offline" and entries[1]["known"] is True
assert entries[2]["message"] == "came online"
i18n.use("it")
assert ha_data.logbook_entries(rows[:1], {}, {})[0]["message"] == "è tornato online"
i18n.use("en")
window = hist.presence_segments("a", now - 86400, now)
slim = ha_data.slim_history(window)
assert all(isinstance(s_["from"], int) and isinstance(s_["to"], int) for s_ in slim["segments"])
assert [s_["online"] for s_ in slim["segments"]] == [True, False] and slim["online_pct"] == window["online_pct"]
print("ok: registro eventi e segmenti")

# 5) localize (flusso SSE) se il router e' importabile qui
try:
    try:
        import httpx  # noqa: F401
    except ImportError:  # in locale puo' mancare: serve solo agli adapter, non a questi controlli
        sys.modules["httpx"] = types.ModuleType("httpx")
    from app import routes_ha
except Exception as exc:  # fastapi o altre dipendenze mancanti in locale: si salta
    print("salto: routes_ha non importabile (%s)" % exc.__class__.__name__)
else:
    ev = routes_ha.localize({"type": "device", "id": "d1", "rev": 3, "device": dev()}, {})
    assert ev["type"] == "device" and ev["rev"] == 3 and ev["device"]["id"] == "d1" and "card" not in ev
    al = routes_ha.localize({"type": "alert", "level": "warning", "key": "alert.new_device", "params": {"label": "X", "ip": "1.2.3.4"}, "rev": 1}, {})
    assert al["message"] == "New device on the network: X (1.2.3.4)" and al["key"] == "alert.new_device" and "params" not in al
    assert routes_ha.localize({"type": "poll", "rev": 1}, {}) == {"type": "poll", "rev": 1}
    assert routes_ha._hours(0) == 1 and routes_ha._hours(10**6) == routes_ha.MAX_HOURS
    assert routes_ha._flag("1") and routes_ha._flag("TRUE") and not routes_ha._flag("0") and not routes_ha._flag(None)
    print("ok: localize SSE e parametri")

    # Le funzioni delle route, chiamate direttamente con uno stato finto.
    import asyncio
    from app.state import state

    class FakeReq:
        query_params = {}
        headers = {}
        cookies = {}

        async def is_disconnected(self):
            return False

    async def fake_new():
        return {"type": "new_devices", "count": 1, "devices": [{"mac": "AA:BB:CC:00:00:09", "ip": "10.0.0.9"}]}

    state.new_devices_event = fake_new
    state.devices = {x["id"]: x for x in devices}
    state.ready.set()
    orig_recent = ha_data.recent_presence
    ha_data.recent_presence = lambda limit: orig_recent(limit, hist)
    routes_ha.history = hist

    async def run_routes():
        r = await routes_ha.api_ha_devices(FakeReq())
        assert r["ready"] is True and [x["id"] for x in r["devices"]] == ["a", "b", "c", "d"] and "rev" in r
        assert r["devices"][2]["type"] == "phone"
        sm = await routes_ha.api_ha_summary(FakeReq())
        assert sm["total"] == 4 and sm["new_devices"]["count"] == 1
        lg = await routes_ha.api_ha_logbook(FakeReq(), limit=5, level="normal")
        assert [e["device_id"] for e in lg["events"]] == ["gone", "a", "a"]
        # Minimo: solo i dispositivi ancora in plancia e non mobili ("gone" non c'e' piu').
        lg = await routes_ha.api_ha_logbook(FakeReq(), limit=5)
        assert [e["device_id"] for e in lg["events"]] == ["a", "a"], lg["events"]
        hs = await routes_ha.api_ha_history_all(hours=24)
        assert set(hs["devices"]) == {"a", "b", "c", "d"} and hs["hours"] == 24
        state.devices["a"] = {**state.devices["a"]}
        h1 = await routes_ha.api_ha_history("a", FakeReq(), hours=24)
        assert h1["device_id"] == "a" and h1["hours"] == 24 and "segments" in h1
        try:
            await routes_ha.api_ha_history("nope", FakeReq(), hours=24)
            raise SystemExit("doveva dare 404")
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404
        resp = await routes_ha.api_ha_events(FakeReq(), rev=0)
        assert resp.media_type == "text/event-stream"
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk)
            if len(chunks) == 4:
                break
        await resp.body_iterator.aclose()
        text = "".join(chunks)
        assert chunks[0] == "retry: 3000\n\n" and "event: poll" in text and "event: activity" in text
        assert "event: new_devices" in text and '"count": 1' in text
        assert not state._subscribers, "la sottoscrizione va chiusa"

    asyncio.run(run_routes())
    print("ok: route /api/ha/* chiamate con stato finto (devices, summary, logbook, history, SSE)")

# 6) traduzioni: stesse chiavi in en e it; tutte le chiavi usate da ha.js ci sono
en = json.loads((ROOT / "app/locales/en/ha.json").read_text(encoding="utf-8"))
it = json.loads((ROOT / "app/locales/it/ha.json").read_text(encoding="utf-8"))
assert set(en) == set(it), sorted(set(en) ^ set(it))
assert all(k.startswith(("ha.", "js.ha.")) for k in en), "solo chiavi ha.* e js.ha.*"
for k in en:  # stessi segnaposto in entrambe le lingue
    assert sorted(re.findall(r"\{(\w+)\}", en[k])) == sorted(re.findall(r"\{(\w+)\}", it[k])), k
src = (ROOT / "app/static/ha/ha.js").read_text(encoding="utf-8")


def have(key):
    return key in en or key + "_one" in en or key + "_other" in en


used = set(re.findall(r'"(js\.ha\.[a-z0-9_.]+)"', src))
missing = sorted(k for k in used if not k.endswith(".") and not k.endswith("_") and not have(k))
assert not missing, missing
types_ = ha_data.TYPE_ORDER
for kind, vals in (("js.ha.type.", types_), ("js.ha.type1.", types_),
                   ("js.ha.badge.", ("online", "offline", "mobile", "new")), ("js.ha.menu.theme_", ("auto", "light", "dark")),
                   ("js.ha.rename.mode_", ("auto", "yes", "no"))):
    for v in vals:
        assert kind + v in en, kind + v
# il loader unisce davvero il file e js_table espone solo js.*
assert i18n.translate("it", "js.ha.network") == "Rete" and i18n.translate("en", "js.ha.network") == "Network"
assert "js.ha.network" in i18n.js_table("it") and "ha.logbook.online" not in i18n.js_table("it")
print("ok: traduzioni (%d chiavi, %d usate da ha.js)" % (len(en), len(used)))

# 7) il tipo dedotto ha un'icona e un'etichetta per ogni valore possibile
icons = (ROOT / "app/static/ha/icons.js").read_text(encoding="utf-8")
for kind in ha_data.TYPE_ORDER:
    assert re.search(r'\b"?%s"?:\s*"[a-z-]+"' % kind, icons), kind
print("ok: icone per tipo")

print("TUTTO OK")
