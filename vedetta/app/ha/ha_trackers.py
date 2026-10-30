"""The clients that a router integration of Home Assistant tracks on the network (UniFi, FRITZ!, MikroTik, nmap...), read from the states of Home Assistant.

Read-ONLY and narrow by construction: of every state, only the device trackers whose source is "router" are kept, and of those only the address, the MAC, the host name,
the name Home Assistant shows and whether the client is at home. A phone tracker (GPS, with coordinates), a person, a zone, anything else is dropped here and never stored or logged.
The trackers that Vedetta itself publishes by MQTT (unique id "vedetta_*") are dropped too: they would be its own data coming back.

The two functions that read are pure (they take what Home Assistant said): the part that talks to Home Assistant is `fetch`, the same Supervisor WebSocket as the registry."""
from . import ha_registry

SOURCE = "router"
TRACKER_DOMAIN = "device_tracker."
OWN_PREFIX = ha_registry.OWN_PREFIX
# The only keys that leave this module, whatever the state carries.
KEPT = ("mac", "ip", "host", "name", "online")


def own_entity_ids(registry: list) -> set:
    """Entity ids of the trackers made by Vedetta (MQTT, unique id "vedetta_*"): to leave out."""
    return {e.get("entity_id") for e in registry if str(e.get("unique_id") or "").startswith(OWN_PREFIX)}


def _online(state) -> bool | None:
    """At home / away; None when Home Assistant does not know ("unavailable", "unknown": an integration that was reloaded says nothing about the client)."""
    if state == "home":
        return True
    if state == "not_home":
        return False
    return None


def _ipv4(value) -> str | None:
    parts = str(value or "").split(".")
    return ".".join(parts) if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


def extract(states: list, own: set = frozenset()) -> list[dict]:
    """The router clients among the states, one row each, in the order Home Assistant lists them (the last one wins when the same MAC is tracked twice). Rows have exactly the keys of KEPT."""
    by_mac: dict = {}
    for st in states:
        row = _row(st, own)
        if row:
            by_mac[row["mac"]] = row
    return list(by_mac.values())


def _row(st: dict, own: set) -> dict | None:
    attrs = st.get("attributes") or {}
    if not _is_router_client(str(st.get("entity_id") or ""), attrs, own):
        return None
    mac = ha_registry.norm_mac(attrs.get("mac"))
    if not mac:
        return None
    return {"mac": mac, "ip": _ipv4(attrs.get("ip")), "host": _text(attrs.get("host_name")), "name": _text(attrs.get("friendly_name")), "online": _online(st.get("state"))}


def _is_router_client(entity: str, attrs: dict, own: set) -> bool:
    return entity.startswith(TRACKER_DOMAIN) and entity not in own and attrs.get("source_type") == SOURCE


def _text(value) -> str | None:
    return str(value or "").strip() or None


async def fetch() -> list[dict]:
    """The router clients now: the states and the registry (to know which trackers are Vedetta's own), through the Supervisor like the registry reading."""
    import websockets
    tok = ha_registry.token()
    if not tok:
        raise RuntimeError("SUPERVISOR_TOKEN assente (fuori da Home Assistant o homeassistant_api spento)")
    async with websockets.connect(ha_registry.WS_URL, max_size=64 * 1024 * 1024, open_timeout=ha_registry.TIMEOUT_S) as ws:
        await ha_registry._authenticate(ws, tok)
        states = await ha_registry._command(ws, 1, "get_states")
        registry = await ha_registry._command(ws, 2, "config/entity_registry/list")
    return extract(states, own_entity_ids(registry))
