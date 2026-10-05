"""Registro di Home Assistant come fonte di nome, marca, modello e area dei dispositivi di rete.

Solo LETTURA, solo comandi WebSocket documentati e non riservati agli amministratori
(config/device_registry/list, config/entity_registry/list, config/area_registry/list, config_entries/get),
tramite il proxy del Supervisor (richiede `homeassistant_api: true` e la variabile SUPERVISOR_TOKEN).
Senza token (fuori da Home Assistant) o con HA spento la fonte e' semplicemente vuota: l'app continua con le
altre. La copia si salva in /data per avere qualcosa anche quando HA e' irraggiungibile.

Il join e' per MAC (connections["mac"]). I dispositivi creati da Vedetta stessa (MQTT, identificativi
"vedetta_*") sono esclusi: sarebbero i suoi stessi dati che tornano indietro."""
import asyncio
import json
import os
import time

from . import paths
from .applog import logger

WS_URL = os.environ.get("VEDETTA_HA_WS", "ws://supervisor/core/websocket")
REFRESH_S = 600
TIMEOUT_S = 20
CACHE_PATH = paths.data_path("ha_registry.json")
OWN_PREFIX = "vedetta_"
# Titoli di integrazione che non sono il nome di un apparecchio (nome del servizio o del router).
GENERIC_TITLES = {"mqtt", "fritz!box", "fritzbox", "home assistant", "shelly", "tasmota", "esphome", "mobile app"}

_state: dict = {"by_mac": {}, "by_ip": {}, "at": 0.0, "error": None, "counts": {}}
_task: asyncio.Task | None = None


def token() -> str | None:
    return os.environ.get("SUPERVISOR_TOKEN") or None


def norm_mac(mac) -> str | None:
    m = str(mac or "").strip().lower().replace("-", ":")
    return m if len(m) == 17 and m.count(":") == 5 else None


def host_of(url) -> str | None:
    """Indirizzo IPv4 dell'indirizzo di configurazione di un dispositivo ("http://192.168.1.2:3000/"), se e' un IP."""
    from urllib.parse import urlparse
    try:
        host = urlparse(str(url or "")).hostname
    except ValueError:
        return None
    parts = (host or "").split(".")
    return host if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


def build_index(devices: list, entities: list, areas: list, entries: list) -> dict:
    """Pura (testabile): registri grezzi di HA -> {"by_mac": {mac: scheda}, "by_ip": {ip: scheda}}. Esclude i dispositivi
    di Vedetta e quelli disabilitati. L'IP viene dall'indirizzo di configurazione (configuration_url) quando il
    dispositivo non ha un MAC (es. AdGuard Home, Proxmox)."""
    area_name = {a.get("area_id"): a.get("name") for a in areas}
    domain_of = {e.get("entry_id"): e.get("domain") for e in entries}
    title_of = {e.get("entry_id"): e.get("title") for e in entries}
    ent_by_dev: dict = {}
    for ent in entities:
        if ent.get("device_id") and not ent.get("disabled_by"):
            ent_by_dev.setdefault(ent["device_id"], []).append(ent)
    out: dict = {}
    out_ip: dict = {}
    ip_count: dict = {}
    for dev in devices:
        if dev.get("disabled_by"):
            continue
        macs = [norm_mac(c[1]) for c in dev.get("connections") or [] if len(c) == 2 and c[0] == "mac"]
        macs = [m for m in macs if m]
        ip = host_of(dev.get("configuration_url"))
        if not macs and not ip:
            continue
        entry_ids = dev.get("config_entries") or []
        domains = sorted({domain_of.get(e) for e in entry_ids if domain_of.get(e)})
        idents = [i for i in dev.get("identifiers") or [] if len(i) == 2]
        # creato da Vedetta (MQTT con identificativo "vedetta_*") e da nessun altro: va escluso
        own = bool(idents) and all(i[0] == "mqtt" and str(i[1]).startswith(OWN_PREFIX) for i in idents) \
            and all(d == "mqtt" for d in domains)
        if own:
            continue
        names = {(e.get("name") or e.get("original_name")) for e in ent_by_dev.get(dev.get("id"), [])
                 if e.get("name") or e.get("original_name")}
        card = {
            "name": dev.get("name_by_user") or dev.get("name"),
            "name_by_user": bool(dev.get("name_by_user")),
            "manufacturer": dev.get("manufacturer"), "model": dev.get("model"),
            "area": area_name.get(dev.get("area_id")),
            "domains": [d for d in domains if d != "mqtt"] or domains,
            "entry_titles": [title_of.get(e) for e in entry_ids if title_of.get(e)],
            "sw_version": dev.get("sw_version"),
            "entity_names": sorted(names)[:6],
        }
        for m in macs:
            out.setdefault(m, card)
        if ip:
            ip_count[ip] = ip_count.get(ip, 0) + 1
            out_ip.setdefault(ip, card)
    # Lo stesso indirizzo condiviso da piu' dispositivi di HA (un host Proxmox con le sue macchine virtuali,
    # tutte con la stessa pagina di gestione) non identifica nessuno di loro: si scarta.
    out_ip = {k: v for k, v in out_ip.items() if ip_count.get(k) == 1}
    return {"by_mac": out, "by_ip": out_ip}


async def _fetch() -> dict:
    import websockets
    tok = token()
    if not tok:
        raise RuntimeError("SUPERVISOR_TOKEN assente (fuori da Home Assistant o homeassistant_api spento)")
    async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024, open_timeout=TIMEOUT_S) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))
        if first.get("type") != "auth_required":
            raise RuntimeError(f"risposta inattesa: {first.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": tok}))
        ok = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))
        if ok.get("type") != "auth_ok":
            raise RuntimeError(f"autenticazione rifiutata: {ok.get('type')}")
        results: dict = {}
        commands = {"devices": "config/device_registry/list", "entities": "config/entity_registry/list",
                    "areas": "config/area_registry/list", "entries": "config_entries/get"}
        for i, (key, cmd) in enumerate(commands.items(), start=1):
            await ws.send(json.dumps({"id": i, "type": cmd}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))
                if msg.get("id") == i:
                    if not msg.get("success"):
                        raise RuntimeError(f"{cmd}: {msg.get('error')}")
                    results[key] = msg.get("result") or []
                    break
        return results


async def refresh() -> bool:
    try:
        raw = await _fetch()
        index = await asyncio.to_thread(build_index, raw["devices"], raw["entities"], raw["areas"], raw["entries"])
        _state.update(by_mac=index["by_mac"], by_ip=index["by_ip"], at=time.time(), error=None,
                      counts={"devices": len(raw["devices"]), "matched_by_mac": len(index["by_mac"]),
                              "matched_by_ip": len(index["by_ip"]), "areas": len(raw["areas"])})
        try:
            CACHE_PATH.write_text(json.dumps({"at": _state["at"], "by_mac": index["by_mac"], "by_ip": index["by_ip"], "counts": _state["counts"]},
                                             ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        logger.info("Registro di Home Assistant letto: %d dispositivi, %d con MAC, %d con IP", len(raw["devices"]), len(index["by_mac"]), len(index["by_ip"]))
        return True
    except Exception as exc:   # HA spento, permesso mancante, rete: mai un errore per l'utente
        _state["error"] = f"{type(exc).__name__}: {exc}"[:200]
        logger.info("Registro di Home Assistant non letto (%s)", _state["error"])
        return False


def _load_cache() -> None:
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        _state.update(by_mac=data.get("by_mac") or {}, by_ip=data.get("by_ip") or {}, at=data.get("at") or 0.0, counts=data.get("counts") or {})
    except (OSError, ValueError):
        pass


async def _loop() -> None:
    while True:
        if not active():
            await asyncio.sleep(30)   # funzione spenta nei flussi: si ricontrolla spesso, parte appena la si accende
            continue
        await refresh()
        await asyncio.sleep(REFRESH_S if _state["error"] is None else REFRESH_S / 2)


def start() -> None:
    global _task
    _load_cache()
    if token() and (_task is None or _task.done()):
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    if _task:
        _task.cancel()


def active() -> bool:
    """True se la funzione "Dati di Home Assistant" e' accesa in almeno un flusso di ricerca (impostazioni)."""
    try:
        from . import settings
        fl = settings.flows_load()
        return "ha_registry" in fl.get("associative", []) or "ha_registry" in fl.get("deep", [])
    except Exception:
        return False


def lookup(mac, ip: str | None = None) -> dict | None:
    """Scheda di HA per quel MAC o, se non c'e', per quell'IP (None se HA non lo conosce o la funzione e' spenta
    nei flussi di ricerca). Il MAC e' piu' sicuro dell'IP, che puo' cambiare."""
    if not active():
        return None
    m = norm_mac(mac)
    return (_state["by_mac"].get(m) if m else None) or (_state["by_ip"].get(ip) if ip else None)


def choose_name(card: dict | None) -> tuple[str | None, str | None]:
    """(nome, fonte) da una scheda di HA: il nome scelto dall'utente in HA vale piu' di tutto (ha_user);
    altrimenti il nome del dispositivo o, se e' tecnico ("shelly1-8CAA..."), il titolo della sua integrazione (ha)."""
    from . import naming
    if not card:
        return None, None
    if card.get("name_by_user") and not naming.is_placeholder(card.get("name")):
        return naming.clean_name(card["name"]), "ha_user"
    for cand in [card.get("name")] + [t for t in card.get("entry_titles") or [] if t]:
        if cand and not naming.is_placeholder(cand) and cand.strip().lower() not in GENERIC_TITLES:
            name = naming.clean_name(cand)
            if name:
                return name, "ha"
    return None, None


def status() -> dict:
    return {"enabled": bool(token()), "last_ok": _state["at"] or None, "error": _state["error"], **_state["counts"]}
