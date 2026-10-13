"""The single MAC layer, phase 1: what the network says about which MAC answers at which address, as plain observations.

An observation is (ip, mac, source, time). Sources are interchangeable and none is required: ARP and mDNS today, DHCP and optional router
queries later. This module only turns what the other modules already know into observations (pure functions, no network, no database);
storage/history_maclayer.py keeps them. Nothing here decides anything yet (phase 2 classifies, phase 3 stabilises conflicts)."""
import asyncio
import time
from collections import Counter, defaultdict
from typing import NamedTuple

from .applog import logger
from . import macclassify, macidentity
from .scan import dhcp, mdns_listener
from .storage.newdevices import normalize_mac


class Observation(NamedTuple):
    ip: str
    mac: str          # normalised: upper case, colons
    source: str       # "arp", "mdns", ...
    ts: float


def from_arp(arp: dict[str, dict], ts: float) -> list[Observation]:
    """{ip: {"mac": ...}} of one ARP view -> observations (entries without a usable MAC are skipped)."""
    out = []
    for ip, host in (arp or {}).items():
        mac = normalize_mac((host or {}).get("mac"))
        if mac and ip:
            out.append(Observation(ip, mac, "arp", ts))
    return out


def from_mdns(cards_by_mac: dict[str, dict], ts: float) -> list[Observation]:
    """The cards remembered by the Bonjour listener (mac -> card with its last IP) -> observations stamped with when each was heard."""
    out = []
    for raw_mac, card in (cards_by_mac or {}).items():
        mac, ip = normalize_mac(raw_mac), (card or {}).get("ip")
        if mac and ip:
            out.append(Observation(ip, mac, "mdns", float(card.get("seen") or ts)))
    return out


def from_dhcp(seen: dict[str, dict], ts: float) -> list[Observation]:
    """The DHCP clients heard on port 67 (chaddr -> entry with the address it uses) -> observations. The chaddr is the client's own MAC even
    behind a repeater that lends its MAC in ARP, which is why this source matters for telling the two apart."""
    out = []
    for raw_mac, entry in (seen or {}).items():
        mac, ip = normalize_mac(raw_mac), (entry or {}).get("ip")
        if mac and ip:                  # stamped with when the ADDRESS was heard (ip_ts); an entry from before ip_ts existed falls back to seen
            out.append(Observation(ip, mac, "dhcp", float(entry.get("ip_ts") or entry.get("seen") or ts)))
    return out


def features_for_linking(rows: list[dict], sessions: list[dict], dhcp_seen: dict[str, dict]) -> dict[str, dict]:
    """What the identity linker needs about each MAC: when it was active (sessions, else first/last), where, and its DHCP name and fingerprint."""
    feats = _activity_by_mac(rows)
    by_mac = _sessions_by_mac(sessions)
    seen = {k.upper(): v for k, v in (dhcp_seen or {}).items()}
    for mac, f in feats.items():
        if by_mac.get(mac):
            f["sessions"] = by_mac[mac]
        f.update(_dhcp_features(seen.get(mac) or {}))
    return feats


def _activity_by_mac(rows: list[dict]) -> dict[str, dict]:
    """First/last time and addresses of each MAC from the observation rows. mDNS says a name was heard, not that the MAC was active, so it is left out."""
    feats: dict[str, dict] = {}
    for r in rows:
        if r["source"] == "mdns":
            continue
        f = feats.setdefault(r["mac"], {"first": 1e18, "last": 0.0, "ips": set()})
        f["first"], f["last"] = min(f["first"], r["first_seen"]), max(f["last"], r["last_seen"])
        f["ips"].add(r["ip"])
    return feats


def _sessions_by_mac(sessions: list[dict]) -> dict[str, list]:
    """(start, end, (ip,)) of the sessions of each MAC, mDNS ones left out."""
    by_mac = defaultdict(list)
    for s in sessions:
        if s["source"] != "mdns":
            by_mac[s["mac"]].append((s["start"], s["end"], (s["ip"],)))
    return by_mac


def _dhcp_features(d: dict) -> dict:
    """Name, client id and fingerprint (vendor class + parameter list, one joint field) that a DHCP entry gives."""
    out = {}
    if d.get("hostname"):
        out["hostname"] = d["hostname"]
    if d.get("client_id"):
        out["client_id"] = d["client_id"]
    if d.get("vendor_class") or d.get("prl"):
        out["fingerprint"] = f"{d.get('vendor_class', '')}|{d.get('prl', '')}"
    return out


def observation_report(history, dhcp_seen: dict, window_days: int = 7) -> dict:
    """Counts only (it goes into the export for the developer): how the classifier and the identity linker read the last `window_days`."""
    since = time.time() - window_days * 86400
    rows, sessions, flips = history.rows(since), history.sessions(since), history.flips(since)
    res = macclassify.classify(rows, sessions, flips)
    feats = features_for_linking(rows, sessions, dhcp_seen)
    zones = Counter(p["zone"] for p in macidentity.link(feats))
    return {"kinds": dict(Counter(v["kind"] for v in res["macs"].values())), "conflicts": len(res["conflicts"]),
            "lenders_with_clients": sum(1 for v in res["macs"].values() if v["kind"] == "lender" and v["behind"]),
            "pairs_by_zone": {z: n for z, n in zones.items() if z != "unrelated"}, "pairs_unrelated": zones.get("unrelated", 0), "flips": len(flips)}


def only_new(observations: list, memory: dict) -> list:
    """Keeps every ARP observation (one per cycle is the point) but a DHCP or mDNS one only when its own timestamp is newer than the one already
    recorded for (source, mac, ip): the listeners keep their last entry in memory and re-reading it every cycle is not a new event."""
    out = []
    for o in observations:
        if o.source == "arp":
            out.append(o)
            continue
        key = (o.source, o.mac, o.ip)
        if o.ts > memory.get(key, -1.0):
            memory[key] = o.ts
            out.append(o)
    if len(memory) > EVENT_MEMORY_MAX:                      # forget the oldest half: an event heard again is merely recorded once more
        for key in sorted(memory, key=memory.get)[:len(memory) // 2]:
            del memory[key]
    return out


_EVENT_MEMORY: dict = {}
EVENT_MEMORY_MAX = 5000


async def record(arp: dict[str, dict], history) -> None:
    """One batch per cycle: what ARP and the Bonjour listener say about which MAC is at which address. Only records, nothing reads it yet,
    and it must never disturb the cycle."""
    try:
        now = time.time()
        rows = only_new(from_arp(arp, now) + from_mdns(mdns_listener.by_mac, now) + from_dhcp(dhcp.seen, now), _EVENT_MEMORY)
        await asyncio.to_thread(history.observe, rows)
    except Exception:
        logger.exception("Registro dei MAC osservati non riuscito")
