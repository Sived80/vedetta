"""The single MAC layer, phase 1: what the network says about which MAC answers at which address, as plain observations.

An observation is (ip, mac, source, time). Sources are interchangeable and none is required: ARP and mDNS today, DHCP and optional router
queries later. This module only turns what the other modules already know into observations (pure functions, no network, no database);
storage/history_maclayer.py keeps them. Every cycle the classifier's verdict on the recent window is stored too (mac_class, ip_conflict) and read
back into macverdict, where the rules that ask whether a MAC is lent find it (1.0 step P2), and the IP conflicts going on (step P3). Nothing here
decides anything."""
import asyncio
import time
from collections import Counter, defaultdict
from typing import NamedTuple

from .applog import logger
from . import macclassify, macidentity, macverdict
from .scan import dhcp, mdns_listener
from .storage.newdevices import normalize_mac


class Observation(NamedTuple):
    ip: str
    mac: str          # normalised: upper case, colons
    source: str       # "arp", "mdns", ...
    ts: float


ARP_SOURCES = ("arp", "arp_dup")     # the first answer to an ARP question, and the other MACs that answered the same question


def from_arp(arp: dict[str, dict], ts: float) -> list[Observation]:
    """{ip: {"mac": ..., "also": [...]}} of one ARP view -> observations (entries without a usable MAC are skipped). The first answer is source
    "arp"; the other MACs that answered the same address ("also", the DUP lines of arp-scan) are source "arp_dup", so the changes of the MAC
    answering an address (ip_flip, made by "arp" alone) stay as they were."""
    out = []
    for ip, host in (arp or {}).items():
        mac = normalize_mac((host or {}).get("mac"))
        if mac and ip:
            out.append(Observation(ip, mac, "arp", ts))
            out += [Observation(ip, m, "arp_dup", ts) for m in dict.fromkeys(map(normalize_mac, host.get("also") or ())) if m and m != mac]
    return out


def from_mdns(cards_by_mac: dict[str, dict], ts: float) -> list[Observation]:
    """The cards remembered by the Bonjour listener (mac -> card with its last IP) -> observations stamped with when each was heard."""
    out = []
    for raw_mac, card in (cards_by_mac or {}).items():
        mac, ip = normalize_mac(raw_mac), (card or {}).get("ip")
        if mac and ip:
            out.append(Observation(ip, mac, "mdns", float(card.get("seen") or ts)))
    return out


NEIGH_STATES = ("REACHABLE", "STALE", "DELAY", "PROBE")


def from_neigh(entries: list[dict], ts: float) -> list[Observation]:
    """The neighbour table of the system (1.0 step P7, source "neigh") -> observations stamped with when the system last CONFIRMED each entry
    (`confirmed_age` seconds before `ts`), never with the time it is read: a STALE entry of a device gone for hours stays on a home network for
    ever. Without that number only a REACHABLE entry counts, as just confirmed. Never read by the verdict (macclassify.ANSWER_SOURCES)."""
    out = []
    for e in entries or ():
        mac, ip, age = normalize_mac(e.get("mac")), e.get("ip"), e.get("confirmed_age")
        if age is None and e.get("state") == "REACHABLE":
            age = 0
        if mac and ip and age is not None and e.get("state") in NEIGH_STATES:
            out.append(Observation(ip, mac, "neigh", ts - age))
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


VERDICT_WINDOW_DAYS = 7     # the stretch of the past the classifier reads, for the stored verdict and for the export alike


def verdict(history, window_days: int = VERDICT_WINDOW_DAYS, now: float | None = None) -> dict:
    """The classifier's reading of the last `window_days` (macclassify.classify over the rows, sessions and flips of the window), each conflict
    with its last evidence (macclassify.last_evidence). Reads only."""
    since = (time.time() if now is None else now) - window_days * 86400
    sessions, flips = history.sessions(since), history.flips(since)
    res = macclassify.classify(history.rows(since), sessions, flips)
    res["conflicts"] = macclassify.last_evidence(res["conflicts"], sessions, flips)
    return res


def observation_report(history, dhcp_seen: dict, window_days: int = VERDICT_WINDOW_DAYS) -> dict:
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
    """Keeps every ARP observation, first answer or not (one per cycle is the point) but a DHCP or mDNS one only when its own timestamp is newer
    than the one already recorded for (source, mac, ip): the listeners keep their last entry in memory and re-reading it every cycle is not a new event."""
    out = []
    for o in observations:
        if o.source in ARP_SOURCES:
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


def _store_verdict_now(history, now: float | None) -> None:
    now = time.time() if now is None else now
    history.store_mac_verdict(verdict(history, now=now), now)
    _read_verdict(history, now)


def _read_verdict(history, now: float) -> None:
    """The stored verdict becomes the one the rules read (macverdict): the single read of mac_class, and of the conflicts that may still be
    going on (ip_conflict)."""
    macverdict.refresh(history.mac_kinds())
    macverdict.refresh_conflicts(history.ip_conflicts(now - macverdict.CONFLICT_OPEN_S))


def load_verdict(history) -> None:
    """At start: the verdict stored by the last run, read before the first cycle (the Bonjour listener starts at once). A failure is only logged."""
    try:
        _read_verdict(history, time.time())
    except Exception:
        logger.exception("Verdetto del livello MAC non letto")


async def store_verdict(history, now: float | None = None) -> None:
    """The verdict of the window, stored (mac_class, ip_conflict) and read back into macverdict; never handed back to the cycle. A failure is only
    logged, and the rules keep the last verdict."""
    try:
        await asyncio.to_thread(_store_verdict_now, history, now)
    except Exception:
        logger.exception("Verdetto del livello MAC non salvato")


_after_verdict: list = []     # the steps that read the fresh verdict and live above this module (step P4: the card links, cardlink_cycle)


def after_verdict(step) -> None:
    """At start (main): `step(history)`, a coroutine function, runs after the verdict of every cycle; registered once."""
    if step not in _after_verdict:
        _after_verdict.append(step)


async def _run_after_verdict(history) -> None:
    for step in _after_verdict:
        try:
            await step(history)
        except Exception:
            logger.exception("Passo dopo il verdetto del livello MAC non riuscito")


async def observe_pass(arp: dict[str, dict], history) -> None:
    """1.0 step P9: what the pass of the "Search devices" button heard, written in ip_mac like an ARP answer of the cycle (the inventory
    reads it at the next cycle); no verdict, that stays with the cycle. Never disturbs the search."""
    try:
        await asyncio.to_thread(history.observe, from_arp(arp, time.time()))
    except Exception:
        logger.exception("Registro dei MAC del tasto non riuscito")


async def record(arp: dict[str, dict], history, neighbours=()) -> None:
    """One batch per cycle: what ARP and the Bonjour listener say about which MAC is at which address, then the verdict of the window stored and
    read back for the rules, then the steps that read it (after_verdict). None must ever disturb the cycle (a failure of one does not stop the others)."""
    try:
        now = time.time()
        rows = only_new(from_arp(arp, now) + from_mdns(mdns_listener.by_mac, now) + from_dhcp(dhcp.seen, now) + from_neigh(neighbours, now), _EVENT_MEMORY)
        await asyncio.to_thread(history.observe, rows)
    except Exception:
        logger.exception("Registro dei MAC osservati non riuscito")
    await store_verdict(history)
    await _run_after_verdict(history)
