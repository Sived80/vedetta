"""Who is behind a card: two different devices answering at the same address.

A card is tied to an address. When the router hands the same address to two devices that are switched on in turn (a laptop and a game
console), the card carries on with the name, brand and type chosen by hand for the first one. That choice is never touched here: this module only
READS what the app already remembers about each MAC (memory per MAC, DHCP, Bonjour, Home Assistant, roles) and, when the evidence is strong,
notes that two different devices have been seen behind the card, so the user can decide. It writes nothing, changes no name, brand or type,
and is silent when it cannot be sure.

The rule (rocky on purpose):
  - "different" needs at least two INDEPENDENT families of evidence that agree (a fact is never counted twice), with real data for both MACs;
  - any veto turns it into "unknown": a private (random) MAC, as phones use; a MAC behind two or more cards at once (a repeater that clones the MAC,
    a NAT); a MAC that belongs to a network role (gateway, access point, repeater);
  - "same" evidence (the same DHCP or Bonjour name, the same Home Assistant device) wins over any difference.
Families of evidence for "different": DHCP family (ChromeOS, PS5, Android, Windows...), recognised group (pc, media...), DHCP name, Bonjour name,
Home Assistant model.
"""
import time

from ..recognition import naming, vendor_lookup
from ..scan import dhcp, mdns_listener
from ..storage.history import history
from . import ha_registry

MIN_FAMILIES = 2
RECHECK_S = 600                       # a card is judged again at most this often (and at once when its MAC changes)
NETWORK_ROLES = {"gateway", "dhcp", "dns", "router", "ap", "repeater"}
_CONSOLES = ("ps3", "ps4", "ps5", "xbox", "nintendo", "playstation")

RESULTS: dict[str, dict] = {}         # card id -> the last verdict "different" (only those are kept)
_checked: dict[str, tuple[str, float]] = {}   # card id -> (MAC when judged, when)
_alerted: set[tuple[str, str, str]] = set()   # (card, mac a, mac b) already notified


# ------------------------------------------------------------------ what we know of a MAC
def family(vendor_class: str | None, prl: str | None = None) -> str | None:
    """Operating system / kind from the DHCP fingerprint of a MAC (None if the data say nothing)."""
    vc = (vendor_class or "").lower().replace(" ", "")
    if any(vc.startswith(c) for c in _CONSOLES):
        return "console"
    return dhcp._os_family(prl, vendor_class)


def _placeholder(name: str | None) -> bool:
    return not name or naming.is_placeholder(name)


def profile(mac: str, mem: dict | None) -> dict:
    """Everything the app remembers about one MAC, live data first, the memory per MAC as a fallback."""
    mem = mem or {}
    d = dhcp.seen.get(mac) or {}
    cls = d.get("vendor_class") or mem.get("dhcp_class")
    dname = d.get("hostname") or mem.get("dhcp_name")
    card = mdns_listener.by_mac.get(mac) or {}
    ha = ha_registry.lookup(mac, None) or {}
    ip = mem.get("ip")
    return {"mac": mac, "ip": ip, "private": dhcp.is_private_mac(mac), "dhcp_class": cls, "family": family(cls, d.get("prl")),
            "dhcp_name": None if _placeholder(dname) else dname.lower(), "grp": mem.get("grp"),
            "mdns_name": (card.get("name") or "").lower() or None,
            "ha": (ha.get("manufacturer"), ha.get("model"), ha.get("name")) if ha else None,
            "vendor": vendor_lookup.lookup_vendor(mac), "first_seen": mem.get("first_seen") or 0}


def _role(ip: str | None) -> bool:
    if not ip:
        return False
    from ..recognition import roles   # late import: roles imports network modules
    return bool(NETWORK_ROLES & set(roles.roles_for(ip)))


# ------------------------------------------------------------------ the judgement (pure)
def judge(a: dict, b: dict, shared: set[str], role_a: bool = False, role_b: bool = False) -> dict:
    """{"verdict": "different" | "same" | "unknown", "reasons": [...], "vetoes": [...]}. Pure: only the two profiles and what is passed in."""
    vetoes = []
    if a["private"] or b["private"]:
        vetoes.append("private")
    if a["mac"] in shared or b["mac"] in shared:
        vetoes.append("shared")
    if role_a or role_b:
        vetoes.append("role")
    if vetoes:
        return {"verdict": "unknown", "reasons": [], "vetoes": vetoes}
    same = []
    if a["dhcp_name"] and a["dhcp_name"] == b["dhcp_name"]:
        same.append("dhcp_name")
    if a["mdns_name"] and a["mdns_name"] == b["mdns_name"]:
        same.append("mdns_name")
    if a["ha"] and a["ha"] == b["ha"] and any(a["ha"]):
        same.append("ha_model")
    if same:
        return {"verdict": "same", "reasons": same, "vetoes": []}
    diff = []
    if a["family"] and b["family"] and a["family"] != b["family"]:
        diff.append("dhcp_family")
    if a["grp"] not in (None, "generic") and b["grp"] not in (None, "generic") and a["grp"] != b["grp"]:
        diff.append("group")
    if a["dhcp_name"] and b["dhcp_name"] and a["dhcp_name"] != b["dhcp_name"]:
        diff.append("dhcp_name")
    if a["mdns_name"] and b["mdns_name"] and a["mdns_name"] != b["mdns_name"]:
        diff.append("mdns_name")
    if a["ha"] and b["ha"] and (a["ha"][0], a["ha"][1]) != (b["ha"][0], b["ha"][1]) and any(a["ha"][:2]) and any(b["ha"][:2]):
        diff.append("ha_model")
    return {"verdict": "different" if len(diff) >= MIN_FAMILIES else "unknown", "reasons": diff, "vetoes": []}


# ------------------------------------------------------------------ the check on a card (runs in a thread: reads the database)
def _shared_macs(last_macs: dict[str, str]) -> set[str]:
    count: dict[str, int] = {}
    for m in last_macs.values():
        k = (m or "").lower()
        count[k] = count.get(k, 0) + 1
    return {m for m, n in count.items() if n >= 2}


def _describe(p: dict) -> dict:
    return {"vendor": p["vendor"], "class": p["dhcp_class"], "family": p["family"], "mac": p["mac"]}


def due(device_id: str, mac: str, now: float) -> bool:
    last = _checked.get(device_id)
    return last is None or last[0] != mac or now - last[1] >= RECHECK_S


def evaluate(device_id: str, mac_now: str, last_macs: dict[str, str], now: float | None = None) -> dict | None:
    """Judges the card: the MAC that had it first against each other MAC seen behind it. Returns the verdict "different" (with
    "new": True the first time it is found for that pair) or None. Nothing is written but the in-memory result."""
    now = time.time() if now is None else now
    mac_now = (mac_now or "").lower()
    _checked[device_id] = (mac_now, now)
    rows = {r["mac"].lower(): r for r in history.mac_memory_for(device_id)}
    if mac_now not in rows:
        rows[mac_now] = {"mac": mac_now, "ip": None, "first_seen": now}
    if len(rows) < 2:
        RESULTS.pop(device_id, None)
        return None
    shared = _shared_macs(last_macs)
    profiles = sorted((profile(m, r) for m, r in rows.items()), key=lambda p: p["first_seen"])
    owner = profiles[0]
    found = None
    for other in profiles[1:]:
        j = judge(owner, other, shared, _role(owner["ip"]), _role(other["ip"]))
        if j["verdict"] == "different":
            found = {"verdict": "different", "a": _describe(owner), "b": _describe(other), "reasons": j["reasons"], "ts": now}
            break
    if not found:
        RESULTS.pop(device_id, None)
        return None
    key = (device_id, found["a"]["mac"], found["b"]["mac"])
    found["new"] = key not in _alerted
    _alerted.add(key)
    RESULTS[device_id] = found
    return found


# ------------------------------------------------------------------ what the card shows
def _label(d: dict) -> str:
    bits = [d.get("vendor"), d.get("class") or d.get("family")]
    return " · ".join(str(x) for x in bits if x) or (d.get("mac") or "?")


def describe(found: dict) -> str:
    return "%s  /  %s" % (_label(found["a"]), _label(found["b"]))


def attrs_for(device_id: str, t) -> list[dict]:
    """Two lines for the device sheet (the translation function is passed in), or nothing."""
    f = RESULTS.get(device_id)
    if not f:
        return []
    why = ", ".join(t("identity_shift.reason." + r) for r in f["reasons"])
    return [{"key": "other_device", "label": t("extra.other_device"), "value": describe(f)},
            {"key": "other_device_why", "label": t("extra.other_device_why"), "value": why}]
