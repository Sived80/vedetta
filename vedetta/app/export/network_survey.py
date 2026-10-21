"""The network survey of the export for the developer: what the host of Vedetta and Home Assistant say about the networks (VLANs) of the house, in a form that
does not depend on a make. It is added to the export only when the person ticks it (and while ENABLED is on) and it goes through the masking and the seal like every
other file. Everything here is a READ: files of the host, the registries Vedetta already reads and ONE template that Home Assistant renders itself, so that a
tracker that is not a router (a phone with a position) never leaves Home Assistant.

  host          interfaces (VLAN sub-interfaces, bridges), their addresses, the default gateway
  clients       the router trackers of Home Assistant: platform, state, address, MAC, name; the names of the attributes each platform gives
  integrations  the platforms that have trackers, how many (enabled / disabled) and the state of their entries (never their titles)
  hierarchy     how many devices say they are connected through another one

Switch it off when its purpose is reached: ENABLED = False hides the tick, the route refuses the request and the export ignores it."""
import asyncio
import datetime
import ipaddress
import json
import unicodedata
from collections import Counter
from pathlib import Path

from .. import iface
from ..applog import logger
from ..ha import ha_registry

ENABLED = True
REVIEW_BY = datetime.date(2027, 4, 30)      # tests/check_network_survey_expiry.py fails after this day while the survey is still on: turn it off or move the date
SECTION_FILE = "state/network_survey.json"
VERSION = 1
MAX_CLIENTS = 2000                   # rows kept; the count stays true
MAX_TEXT = 64                        # a name is free text: cut it
TEMPLATE_TIMEOUT_S = 20
RECV_TIMEOUT_S = 25
SYS_NET = Path("/sys/class/net")
PROC = Path("/proc")

# The filter runs inside Home Assistant: only the trackers of a router are listed, with the four fields and the NAMES of their attributes.
TEMPLATE = ("{% set ns = namespace(rows=[]) %}"
            "{% for s in states.device_tracker if s.attributes.get('source_type') == 'router' %}"
            "{% set ns.rows = ns.rows + [{'entity_id': s.entity_id, 'state': s.state, 'ip': s.attributes.get('ip'), 'mac': s.attributes.get('mac'),"
            " 'host_name': s.attributes.get('host_name'), 'keys': s.attributes.keys() | map('string') | list}] %}"
            "{% endfor %}{{ ns.rows | tojson }}")


class SurveyError(RuntimeError):
    """Home Assistant could not answer the survey: the export goes on without it and says so in its notes."""


# ------------------------------------------------------------------ the host
def parse_vlan_config(text: str) -> dict[str, dict]:
    """/proc/net/vlan/config: 'eth0.10 | 10 | eth0' -> {name: {id, parent}} (the header lines and anything odd are skipped)."""
    out = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[1].isdigit():
            out[parts[0]] = {"id": int(parts[1]), "parent": parts[2]}
    return out


def default_gateway(route_text: str) -> str | None:
    """The gateway of the default route (/proc/net/route keeps it as little-endian hex)."""
    name = iface.parse_default_route(route_text)
    for line in route_text.splitlines()[1:]:
        f = line.split()
        if name and len(f) >= 8 and f[0] == name and f[1] == "00000000" and f[7] == "00000000":
            return ".".join(str(b) for b in reversed(bytes.fromhex(f[2])))
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError as exc:
        logger.debug("network survey: %s not readable (%s)", path, exc)
        return ""


def _ipv4_addresses(name: str) -> list[dict]:
    """The first IPv4 address of an interface and its prefix (the kernel call BusyBox tools use); none on a system without it."""
    try:
        import fcntl
        import socket
        import struct
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            packed = struct.pack("256s", name.encode()[:15])
            address = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, packed)[20:24])        # SIOCGIFADDR
            mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x891B, packed)[20:24])           # SIOCGIFNETMASK
    except (ImportError, OSError) as exc:                                    # no such module (not Linux) or an interface without an IPv4 address
        logger.debug("network survey: no IPv4 for %s (%s)", name, exc)
        return []
    return [{"address": address, "prefix": ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen}]


def _kind(path: Path, vlans: dict) -> str:
    if path.name == "lo":
        return "loopback"
    if (path / "bridge").is_dir():
        return "bridge"
    return "vlan" if path.name in vlans else "other"


def _interface(path: Path, vlans: dict, ipv4_of) -> dict:
    item = {"name": path.name, "kind": _kind(path, vlans), "state": _read(path / "operstate").strip() or None,
            "mac": _read(path / "address").strip() or None, "ipv4": ipv4_of(path.name)}
    if path.name in vlans:
        item["vlan"] = vlans[path.name]
    return item


def read_host(sys_net: Path = SYS_NET, proc: Path = PROC, ipv4_of=None) -> dict:
    """Interfaces, default interface and gateway of the host, from files only."""
    vlans = parse_vlan_config(_read(proc / "net" / "vlan" / "config"))
    route = _read(proc / "net" / "route")
    paths = sorted(sys_net.iterdir()) if sys_net.is_dir() else []
    return {"interfaces": [_interface(p, vlans, ipv4_of or _ipv4_addresses) for p in paths],
            "default_interface": iface.parse_default_route(route), "gateway": default_gateway(route)}


# ------------------------------------------------------------------ Home Assistant
def parse_template_result(result) -> list[dict]:
    """The rows the template made. Home Assistant may hand the text over or already parsed; anything that is not a list of rows is no answer."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            logger.debug("network survey: the template answer is not JSON")
            return []
    return [r for r in result if isinstance(r, dict)] if isinstance(result, list) else []


def _rows_of(msg: dict) -> list[dict] | None:
    """The rows an answer to the template carries; None for any other message (the id of another command, the first 'result' that only says yes). An error raises."""
    if msg.get("id") != 1:
        return None
    if msg.get("type") == "result" and not msg.get("success"):
        raise SurveyError(f"render_template: {msg.get('error')}")
    if msg.get("type") != "event":
        return None
    event = msg.get("event") or {}
    if "error" in event:
        raise SurveyError(f"render_template: {event['error']}")
    return parse_template_result(event.get("result"))


async def fetch_trackers(ws) -> list[dict]:
    """Asks Home Assistant to render the template (the only thing this survey ever sends) and reads the answer."""
    await ws.send(json.dumps({"id": 1, "type": "render_template", "template": TEMPLATE, "timeout": TEMPLATE_TIMEOUT_S, "report_errors": True}))
    while True:
        rows = _rows_of(json.loads(await asyncio.wait_for(ws.recv(), RECV_TIMEOUT_S)))
        if rows is not None:
            return rows


def _clean_text(value, limit: int = MAX_TEXT) -> str | None:
    """Free text of a device: no control or format characters (they hide and reorder text), cut short, None when nothing is left."""
    text = "".join(c for c in str(value or "") if unicodedata.category(c) not in ("Cc", "Cf")).strip()
    return text[:limit] or None


def _valid_ip(value) -> str | None:
    try:
        return str(ipaddress.ip_address(str(value)))
    except ValueError:
        return None


def _own_entity_ids(entities: list, devices: list, entries: list) -> set[str]:
    """The trackers Vedetta itself made (MQTT, 'vedetta_*'): they are its own data coming back, not clients."""
    domain_of = {e.get("entry_id"): e.get("domain") for e in entries}
    own = {d["id"] for d in devices if ha_registry._made_by_vedetta(d, [domain_of[c] for c in d.get("config_entries") or [] if domain_of.get(c)])}
    return {e["entity_id"] for e in entities if e.get("device_id") in own}


def _state_bucket(state) -> str:
    return state if state in ("home", "not_home") else "other"


def _state_counts(rows: list) -> dict:
    counts = Counter(_state_bucket(r.get("state")) for r in rows)
    return {name: counts.get(name, 0) for name in ("home", "not_home", "other")}


def _attribute_keys(rows: list, platform_of: dict) -> dict:
    """The NAMES of the attributes each platform gives its trackers (never their values)."""
    keys: dict[str, set] = {}
    for r in rows:
        keys.setdefault(_platform(r, platform_of), set()).update(filter(None, (_clean_text(k, 40) for k in r.get("keys") or [])))
    return {platform: sorted(names) for platform, names in keys.items()}


def _platform(row: dict, platform_of: dict) -> str:
    return platform_of.get(row.get("entity_id"), "unknown")


def _client_row(row: dict, platform: str) -> dict:
    return {"platform": platform, "state": _clean_text(row.get("state"), 20), "ip": _valid_ip(row.get("ip")),
            "mac": ha_registry.norm_mac(row.get("mac")), "host_name": _clean_text(row.get("host_name"))}


def clients_section(rows: list, entities: list, devices: list, entries: list, limit: int = MAX_CLIENTS) -> dict:
    platform_of = {e.get("entity_id"): e.get("platform") or "unknown" for e in entities}
    own = _own_entity_ids(entities, devices, entries)
    mine = [r for r in rows if r.get("entity_id") not in own]
    return {"count": len(mine), "truncated": len(mine) > limit, "states": _state_counts(mine),
            "by_platform": dict(Counter(_platform(r, platform_of) for r in mine)), "attribute_keys": _attribute_keys(mine, platform_of),
            "rows": [_client_row(r, _platform(r, platform_of)) for r in mine[:limit]]}


def _trackers_of(entities: list, platform: str) -> list:
    return [e for e in entities if e.get("platform") == platform and str(e.get("entity_id", "")).startswith("device_tracker.")]


def _entry_states(entries: list, platform: str) -> dict:
    return dict(Counter(str(e.get("state") or "unknown") for e in entries if e.get("domain") == platform))


def integrations_section(entities: list, entries: list, platforms) -> dict:
    out = {}
    for platform in sorted(p for p in platforms if p != "unknown"):
        trackers = _trackers_of(entities, platform)
        out[platform] = {"trackers": len(trackers), "disabled": sum(1 for e in trackers if e.get("disabled_by")), "entries": _entry_states(entries, platform)}
    return out


def hierarchy_section(devices: list) -> dict:
    return {"devices": len(devices), "with_via_device": sum(1 for d in devices if d.get("via_device_id"))}


def build(host: dict, rows: list, registry: dict, limit: int = MAX_CLIENTS) -> dict:
    """The file: host, clients, integrations, hierarchy. Nothing in it names an entity or an entry."""
    entities, devices, entries = registry.get("entities") or [], registry.get("devices") or [], registry.get("entries") or []
    clients = clients_section(rows, entities, devices, entries, limit)
    return {"version": VERSION, "host": host, "clients": clients, "integrations": integrations_section(entities, entries, clients["by_platform"]),
            "hierarchy": hierarchy_section(devices)}


# ------------------------------------------------------------------ masking
def _register_host(anon, host: dict) -> None:
    for item in host.get("interfaces") or []:
        anon.add_mac(item.get("mac"))
        for a in item.get("ipv4") or []:
            anon.add_ip(a.get("address"))
    anon.add_ip(host.get("gateway"))


def _register_clients(anon, rows: list) -> None:
    for r in rows:
        anon.add_ip(r.get("ip"))
        anon.add_mac(r.get("mac"))
    anon.add_devices([([r["host_name"]], None, None, None) for r in rows if r.get("host_name")])      # together: a name two clients share must not merge them


def register_for_masking(anon, survey: dict) -> None:
    """Tells the masking about every address, MAC and name the survey holds, before the files are masked (the names of the clients are free text:
    the masking only knows the ones it is told)."""
    _register_host(anon, survey.get("host") or {})
    _register_clients(anon, (survey.get("clients") or {}).get("rows") or [])


# ------------------------------------------------------------------ the export
async def _read_home_assistant() -> tuple[dict, list]:
    import websockets
    tok = ha_registry.token()
    if not tok:
        raise SurveyError("no token: outside Home Assistant, or homeassistant_api is off")
    registry = await ha_registry._fetch()
    async with websockets.connect(ha_registry.WS_URL, max_size=64 * 1024 * 1024, open_timeout=ha_registry.TIMEOUT_S) as ws:
        await ha_registry._authenticate(ws, tok)
        return registry, await fetch_trackers(ws)


def collect() -> tuple[dict, str | None]:
    """(the survey, a note for the manifest when Home Assistant could not be read). Blocking: the export runs in its own thread."""
    host, registry, rows, note = read_host(), {}, [], None
    try:
        registry, rows = asyncio.run(_read_home_assistant())
    except Exception as exc:        # HA down, a missing permission, an answer that is no answer: the host part still goes in
        logger.warning("network survey: Home Assistant not read (%s: %s)", type(exc).__name__, str(exc)[:120])
        note = f"Home Assistant not read ({type(exc).__name__})"
    return build(host, rows, registry), note


def add_to(p) -> None:
    """The hook of the export: when the person asked for it, and while the switch is on, the survey becomes a file of the export."""
    if not (ENABLED and p.want_survey):
        return
    survey, note = collect()
    p.survey = survey
    p.add(SECTION_FILE, json.dumps(survey, ensure_ascii=False, indent=1))
    p.manifest["survey"] = {"clients": survey["clients"]["count"], "interfaces": len(survey["host"]["interfaces"])}
    if note:
        p.manifest["notes"].append("network survey: " + note)
