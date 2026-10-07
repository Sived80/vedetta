"""Home Assistant registry as a source of name, brand, model and area of the network devices.

Read-ONLY, only documented WebSocket commands not reserved to administrators
(config/device_registry/list, config/entity_registry/list, config/area_registry/list, config_entries/get),
through the Supervisor proxy (requires `homeassistant_api: true` and the SUPERVISOR_TOKEN variable).
Without a token (outside Home Assistant) or with HA down the source is simply empty: the app carries on with the
others. The copy is saved in /data to have something even when HA is unreachable.

The join is by MAC (connections["mac"]). Devices created by Vedetta itself (MQTT, identifiers
"vedetta_*") are excluded: they would be its own data coming back."""
import asyncio
import json
import os
import time

from .. import paths
from ..applog import logger

WS_URL = os.environ.get("VEDETTA_HA_WS", "ws://supervisor/core/websocket")
REFRESH_S = 600
TIMEOUT_S = 20
CACHE_PATH = paths.data_path("ha_registry.json")
OWN_PREFIX = "vedetta_"
# Integration titles that are not the name of a device (name of the service or of the router).
GENERIC_TITLES = {"mqtt", "fritz!box", "fritzbox", "home assistant", "shelly", "tasmota", "esphome", "mobile app"}

_state: dict = {"by_mac": {}, "by_ip": {}, "at": 0.0, "error": None, "counts": {}}
_task: asyncio.Task | None = None


def token() -> str | None:
    return os.environ.get("SUPERVISOR_TOKEN") or None


def norm_mac(mac) -> str | None:
    m = str(mac or "").strip().lower().replace("-", ":")
    return m if len(m) == 17 and m.count(":") == 5 else None


def host_of(url) -> str | None:
    """IPv4 address of the configuration address of a device ("http://192.168.1.2:3000/"), if it is an IP."""
    from urllib.parse import urlparse
    try:
        host = urlparse(str(url or "")).hostname
    except ValueError:
        return None
    parts = (host or "").split(".")
    return host if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


def build_index(devices: list, entities: list, areas: list, entries: list) -> dict:
    """Pure (testable): raw HA registries -> {"by_mac": {mac: record}, "by_ip": {ip: record}}. Excludes the devices
    of Vedetta and the disabled ones. The IP comes from the configuration address (configuration_url) when the
    device has no MAC (e.g. AdGuard Home, Proxmox)."""
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
        # created by Vedetta (MQTT with "vedetta_*" identifier) and by nobody else: it must be excluded
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
            # kinds of entities of the device (device_tracker, sensor...): a client that a router integration only tracks has just device_tracker
            "entity_domains": sorted({str(e.get("entity_id") or "").split(".")[0] for e in ent_by_dev.get(dev.get("id"), []) if e.get("entity_id")}),
        }
        for m in macs:
            out.setdefault(m, card)
        if ip:
            ip_count[ip] = ip_count.get(ip, 0) + 1
            out_ip.setdefault(ip, card)
    # The same address shared by several HA devices (a Proxmox host with its virtual machines,
    # all with the same management page) does not identify any of them: it is discarded.
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
    except Exception as exc:   # HA down, missing permission, network: never an error for the user
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
            await asyncio.sleep(30)   # function off in the flows: it rechecks often, starts as soon as it is turned on
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
    """True if the "Home Assistant data" function is on in at least one search flow (settings)."""
    try:
        from ..storage import settings
        fl = settings.flows_load()
        return "ha_registry" in fl.get("associative", []) or "ha_registry" in fl.get("deep", [])
    except Exception:
        return False


def lookup(mac, ip: str | None = None) -> dict | None:
    """HA record for that MAC or, if there is none, for that IP (None if HA does not know it or the function is off
    in the search flows). The MAC is safer than the IP, which can change."""
    if not active():
        return None
    m = norm_mac(mac)
    return (_state["by_mac"].get(m) if m else None) or (_state["by_ip"].get(ip) if ip else None)


def choose_name(card: dict | None) -> tuple[str | None, str | None]:
    """(name, source) from an HA record: the name chosen by the user in HA counts above everything (ha_user);
    otherwise the device name or, if it is technical ("shelly1-8CAA..."), the title of its integration (ha)."""
    from ..recognition import naming
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
