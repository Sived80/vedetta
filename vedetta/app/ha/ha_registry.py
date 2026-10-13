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
from functools import lru_cache

from .. import datafile, paths
from ..applog import logger
from ..recognition import naming
from ..storage import settings
import contextlib

WS_URL = os.environ.get("VEDETTA_HA_WS", "ws://supervisor/core/websocket")
REFRESH_S = 600
TIMEOUT_S = 20
CACHE_PATH = paths.data_path("ha_registry.json")
OWN_PREFIX = "vedetta_"
# Integration titles that are not the name of a device (name of the service or of the router).


@lru_cache(maxsize=1)
def _generic_titles() -> frozenset:
    """Titles of config entries that name the integration, not the device (data/ha_integrations.json; none when the file cannot be read: told once in the log)."""
    return frozenset(datafile.read(datafile.DATA_DIR / "ha_integrations.json", "generic_titles", what="Table of Home Assistant integrations", default=[]))


@lru_cache(maxsize=1)
def observer_domains() -> frozenset:
    """The integrations that OBSERVE the network (data/ha_integrations.json, "observer": UniFi, MikroTik, FRITZ!...): they make entities for the clients they see, which says the device is on the network, not what it is."""
    rows = datafile.read(datafile.DATA_DIR / "ha_integrations.json", "integrations", what="Table of Home Assistant integrations", default={})
    return frozenset(domain for domain, row in rows.items() if row.get("observer"))


def observed_only(card: dict, observers) -> bool:
    """True when the observer integrations of the card only SEE the device. They own it only when the registry holds a product of its own - a model or a firmware version - and every integration
    of the device is an observer (otherwise another one owns the device and the model is its own). Seen in two makers' exports: the network equipment has a model and a firmware, its clients have neither.
    A registry saved before it told the product (no such key at all) says nothing: as it always was."""
    if "model" not in card and "sw_version" not in card:
        return False
    owned = (card.get("model") or card.get("sw_version")) and all(d in observers for d in card.get("domains") or [])
    return not owned


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
    ent_by_dev = _entities_by_device(entities)
    out: dict = {}
    out_ip: dict = {}
    ip_count: dict = {}
    for dev in devices:
        found = _indexed_card(dev, area_name, domain_of, title_of, ent_by_dev)
        if found is None:
            continue
        card, macs, ip = found
        for m in macs:
            out.setdefault(m, card)
        if ip:
            ip_count[ip] = ip_count.get(ip, 0) + 1
            out_ip.setdefault(ip, card)
    # The same address shared by several HA devices (a Proxmox host with its virtual machines,
    # all with the same management page) does not identify any of them: it is discarded.
    out_ip = {k: v for k, v in out_ip.items() if ip_count.get(k) == 1}
    return {"by_mac": out, "by_ip": out_ip}


def _entities_by_device(entities: list) -> dict:
    by_dev: dict = {}
    for ent in entities:
        if ent.get("device_id") and not ent.get("disabled_by"):
            by_dev.setdefault(ent["device_id"], []).append(ent)
    return by_dev


def _indexed_card(dev: dict, area_name: dict, domain_of: dict, title_of: dict, ent_by_dev: dict):
    """(card, MACs, configuration address) of a device worth indexing, or None: disabled, with neither a MAC nor an address, or made by Vedetta."""
    if dev.get("disabled_by"):
        return None
    macs, ip = _macs_of(dev), host_of(dev.get("configuration_url"))
    if not macs and not ip:
        return None
    entry_ids = dev.get("config_entries") or []
    domains = sorted({domain_of.get(e) for e in entry_ids if domain_of.get(e)})
    if _made_by_vedetta(dev, domains):
        return None
    return _card(dev, domains, entry_ids, area_name, title_of, ent_by_dev.get(dev.get("id"), []), _observer_titles(dev, domains, entry_ids, domain_of, title_of)), macs, ip


def _observer_titles(dev: dict, domains: list, entry_ids: list, domain_of: dict, title_of: dict) -> list:
    """The titles of the observer entries that only see this device (the name of the router or of the controller, not of the device); none for the equipment itself."""
    observers = observer_domains()
    if not observed_only({"model": dev.get("model"), "sw_version": dev.get("sw_version"), "domains": domains}, observers):
        return []
    return [title_of[e] for e in entry_ids if domain_of.get(e) in observers and title_of.get(e)]


def _macs_of(dev: dict) -> list[str]:
    macs = [norm_mac(c[1]) for c in dev.get("connections") or [] if len(c) == 2 and c[0] == "mac"]
    return [m for m in macs if m]


def _made_by_vedetta(dev: dict, domains: list) -> bool:
    """Created by Vedetta (MQTT with a "vedetta_*" identifier) and by nobody else: it must be excluded."""
    idents = [i for i in dev.get("identifiers") or [] if len(i) == 2]
    return bool(idents) and all(i[0] == "mqtt" and str(i[1]).startswith(OWN_PREFIX) for i in idents) and all(d == "mqtt" for d in domains)


def _card(dev: dict, domains: list, entry_ids: list, area_name: dict, title_of: dict, ents: list, observer_titles: list) -> dict:
    """What the registry says about one device, in the shape the rest of the app reads."""
    return {
        "name": dev.get("name_by_user") or dev.get("name"),
        "name_by_user": bool(dev.get("name_by_user")),
        "manufacturer": dev.get("manufacturer"), "model": dev.get("model"),
        "area": area_name.get(dev.get("area_id")),
        "domains": [d for d in domains if d != "mqtt"] or domains,
        "entry_titles": [title_of.get(e) for e in entry_ids if title_of.get(e)],
        "observer_titles": observer_titles,
        "sw_version": dev.get("sw_version"),
        "entity_names": _entity_names(ents),
        "entity_domains": _entity_domains(ents),
    }


def _entity_names(ents: list) -> list:
    """The names of the entities of a device (up to six, sorted)."""
    names = {(e.get("name") or e.get("original_name")) for e in ents if e.get("name") or e.get("original_name")}
    return sorted(names)[:6]


def _entity_domains(ents: list) -> list:
    """Kinds of entities of the device (device_tracker, sensor...): a client that a router integration only tracks has just device_tracker."""
    return sorted({str(e.get("entity_id") or "").split(".")[0] for e in ents if e.get("entity_id")})


async def refresh() -> bool:
    try:
        raw = await _fetch()
        index = await asyncio.to_thread(build_index, raw["devices"], raw["entities"], raw["areas"], raw["entries"])
        _state.update(by_mac=index["by_mac"], by_ip=index["by_ip"], at=time.time(), error=None,
                      counts={"devices": len(raw["devices"]), "matched_by_mac": len(index["by_mac"]),
                              "matched_by_ip": len(index["by_ip"]), "areas": len(raw["areas"])})
        with contextlib.suppress(OSError):
            CACHE_PATH.write_text(json.dumps({"at": _state["at"], "by_mac": index["by_mac"], "by_ip": index["by_ip"], "counts": _state["counts"]},
                                             ensure_ascii=False), encoding="utf-8")
        logger.info("Registro di Home Assistant letto: %d dispositivi, %d con MAC, %d con IP", len(raw["devices"]), len(index["by_mac"]), len(index["by_ip"]))
        return True
    except Exception as exc:   # HA down, missing permission, network: never an error for the user
        _state["error"] = f"{type(exc).__name__}: {exc}"[:200]
        logger.info("Registro di Home Assistant non letto (%s)", _state["error"])
        return False


_COMMANDS = {"devices": "config/device_registry/list", "entities": "config/entity_registry/list",
             "areas": "config/area_registry/list", "entries": "config_entries/get"}


async def _fetch() -> dict:
    import websockets
    tok = token()
    if not tok:
        raise RuntimeError("SUPERVISOR_TOKEN assente (fuori da Home Assistant o homeassistant_api spento)")
    async with websockets.connect(WS_URL, max_size=64 * 1024 * 1024, open_timeout=TIMEOUT_S) as ws:
        await _authenticate(ws, tok)
        return {key: await _command(ws, i, cmd) for i, (key, cmd) in enumerate(_COMMANDS.items(), start=1)}


async def _receive(ws) -> dict:
    return json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))


async def _authenticate(ws, tok: str) -> None:
    """The greeting of Home Assistant, then the token; an error that says what came instead."""
    first = await _receive(ws)
    if first.get("type") != "auth_required":
        raise RuntimeError(f"risposta inattesa: {first.get('type')}")
    await ws.send(json.dumps({"type": "auth", "access_token": tok}))
    ok = await _receive(ws)
    if ok.get("type") != "auth_ok":
        raise RuntimeError(f"autenticazione rifiutata: {ok.get('type')}")


async def _command(ws, number: int, cmd: str) -> list:
    """Asks one registry; the answer with the same id is the one that counts (events that arrive in between are skipped)."""
    await ws.send(json.dumps({"id": number, "type": cmd}))
    while True:
        msg = await _receive(ws)
        if msg.get("id") != number:
            continue
        if not msg.get("success"):
            raise RuntimeError(f"{cmd}: {msg.get('error')}")
        return msg.get("result") or []


def start() -> None:
    global _task
    _load_cache()
    if token() and (_task is None or _task.done()):
        _task = asyncio.create_task(_loop())


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


async def stop() -> None:
    if _task:
        _task.cancel()


def active() -> bool:
    """True if the "Home Assistant data" function is on in at least one search flow (settings)."""
    try:
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
    if not card:
        return None, None
    if _chosen_by_user(card):
        return naming.clean_name(card["name"]), "ha_user"
    for cand in _candidate_names(card):
        name = _usable_name(cand)
        if name:
            return name, "ha"
    return None, None


def _chosen_by_user(card: dict) -> bool:
    """The name was set by hand in HA and is not a default system name."""
    return bool(card.get("name_by_user")) and not naming.is_placeholder(card.get("name"))


def tracker_only(card: dict) -> bool:
    """Home Assistant knows the device only through a device_tracker: a client that some integration (a router, a presence tracker...) saw on the network.
    That says it is on the network, not what it is. Only a device with other entities (sensors, switches, players, cameras...) is declared by its integration."""
    return card.get("entity_domains") is not None and not (set(card["entity_domains"]) - {"device_tracker"})


def _candidate_names(card: dict) -> list:
    """The device name first, then the titles of its integrations (empty ones left out). The title of the integration that only tracks the client
    (a router) is the name of the router, not of the client: it is not offered; neither are the titles of the observers that only see the device (observer_titles)."""
    seen_only = set(card.get("observer_titles") or [])
    titles = [] if tracker_only(card) else [t for t in card.get("entry_titles") or [] if t and t not in seen_only]
    return [card.get("name")] + titles


def _usable_name(cand: str | None) -> str | None:
    """The cleaned candidate, or None when it is empty, a default system name, a generic integration title, or cleans to nothing."""
    if not cand or naming.is_placeholder(cand) or cand.strip().lower() in _generic_titles():
        return None
    return naming.clean_name(cand)


def status() -> dict:
    return {"enabled": bool(token()), "last_ok": _state["at"] or None, "error": _state["error"], **_state["counts"]}
