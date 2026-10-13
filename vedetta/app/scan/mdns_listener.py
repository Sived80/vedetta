"""Memory and continuous listening of Bonjour (mDNS) names, like the DHCP memory.

Many devices (iPhones, tablets) announce their name only when they are awake: a scan of a few
seconds often misses them. Here it is done in two ways:
- continuous listening: an always-on DNS-SD browser (zeroconf) collects the announcements as soon as they arrive;
- memory: every name seen (even from a scan) is remembered per MAC in /data/mdns_seen.json and is not lost
  when the device goes back to sleep.

The name arrives with an IP: it is tied to the MAC through the ARP table; if the MAC is not known yet it is kept by IP
(valid for 14 days, an IP can change owner). Passive reading only: no request targeted at a device."""
import asyncio
import json
import re
import time

from .. import paths
from ..atomic import write_atomic
from . import mdns_parse, scan_common
from .mdns_browsing import Browsing
from ..applog import logger
from ..formatters import truncate_name
import contextlib

STORE_PATH = paths.data_path("mdns_seen.json")
IP_TTL_S = 14 * 86400
_NAME_STRONG = 3   # score of a user-chosen name (friendly_name / service with a user name)

by_mac: dict[str, dict] = {}   # lowercase mac -> {"name", "score", "model", "manufacturer", "services", "ip", "seen"}
by_ip: dict[str, dict] = {}    # ip -> same card, until the MAC is known
_mac_for_ip = lambda ip: None  # noqa: E731  (set by start)
_at_several_addresses = lambda mac: False  # noqa: E731  (set by start: the MAC answers at several addresses RIGHT NOW)
_lent_counts = None  # set by start: a function (since) -> {MAC: how many addresses the MAC layer saw it at after `since`}; none = no memory, only the table of the moment

# A repeater lends its MAC to the clients behind it, but only the ones that are awake are in the ARP table: judging by the table of the moment, a MAC is «lent» while a phone behind the repeater is
# on and «its own» when the phone sleeps, and the card of the repeater turned from router to phone and back (the phone's Bonjour announcements were filed under the repeater's MAC). The memory of the MAC layer
# keeps the answer: a MAC seen at LENT_MIN_ADDRESSES or more addresses in the last LENT_WINDOW_S is lent, whoever is awake. Two addresses only can be one device that changed address (a new lease), so they do not count.
LENT_MIN_ADDRESSES = 3
LENT_WINDOW_S = 7 * 86400
LENT_REFRESH_S = 300
_lent_memory: dict = {"ts": 0.0, "macs": frozenset()}


def lent_in_memory(mac: str, now: float | None = None) -> bool:
    """Was this MAC seen at several addresses in the last days? The count is read again at most every LENT_REFRESH_S; if it cannot be read the last answer stands."""
    if _lent_counts is None:
        return False
    now = time.time() if now is None else now
    if now - _lent_memory["ts"] > LENT_REFRESH_S:
        try:
            counts = _lent_counts(now - LENT_WINDOW_S)
            _lent_memory["macs"] = frozenset(str(m).lower() for m, n in counts.items() if n >= LENT_MIN_ADDRESSES)
        except Exception:
            logger.debug("Memory of the lent MACs not read", exc_info=True)
        _lent_memory["ts"] = now
    return str(mac).lower() in _lent_memory["macs"]


def _is_lent_mac(mac: str) -> bool:
    """A MAC that a repeater lends to several addresses: now in the ARP table, or in the memory of the last days."""
    return bool(mac) and (_at_several_addresses(mac) or lent_in_memory(mac))
_task: asyncio.Task | None = None
_dirty = False


def score_name(stype: str, instance: str, txt: str) -> tuple[int, str]:
    """(score, name) of an announcement: same choice as the scan (TXT keys, services with a user name)."""
    score, value = (2 if stype in mdns_parse._MDNS_USER_NAMED else 1), instance
    for key, key_score in mdns_parse._MDNS_NAME_KEYS:
        m = re.search(key + r'=([^"]*)', txt)
        if m and m.group(1) and not mdns_parse._MDNS_SLUG_RE.match(m.group(1)):
            return key_score, m.group(1)
    return score, value


def record(ip: str, stype: str, instance: str, txt: str, now: float | None = None) -> None:
    """Remembers an announcement (called both by continuous listening and by the scan)."""
    global _dirty
    if not scan_common.is_valid_ipv4(ip):
        return
    now = time.time() if now is None else now
    score, name = score_name(stype, instance, txt)
    meta = mdns_parse.parse_mdns_txt(txt)
    mac = _own_mac(ip)
    card = _updated_card(by_mac.get(mac) if mac else by_ip.get(ip), stype, name, score, meta, ip, now)
    if mac:
        by_mac[mac] = card
        by_ip.pop(ip, None)
    else:
        by_ip[ip] = card
    _dirty = True


def _own_mac(ip: str) -> str | None:
    """The MAC that identifies the device at this address, or None: unknown yet, or lent by a repeater to several addresses (it names none of them)."""
    mac = _mac_for_ip(ip)
    return None if mac and _is_lent_mac(mac) else mac


def _updated_card(card: dict | None, stype: str, name: str, score: int, meta: dict, ip: str, now: float) -> dict:
    """A copy of the card remembered for a device, updated with one announcement: the service is added, a better name replaces the old one
    (on equal score the most recent wins), model and manufacturer are filled when the announcement has them, address and time are renewed."""
    card = dict(card or {})
    services = set(card.get("services") or []) | {stype}
    if score >= int(card.get("score") or 0):
        card.update(name=truncate_name(name), score=score)
    for key in ("model", "manufacturer"):
        if meta.get(key):
            card[key] = meta[key]
    card.update(services=sorted(services), ip=ip, seen=now)
    return card


def remember_scan(found: list[tuple[str, str, str, str]]) -> None:
    """Announcements collected by an mDNS scan (type, instance, ip, txt)."""
    for stype, instance, ip, txt in found:
        record(ip, stype, instance, txt)


def lookup(mac, ip: str | None = None) -> dict | None:
    """Card remembered for that MAC or, if missing, for that IP (recent). None if never seen."""
    m = str(mac or "").strip().lower().replace("-", ":")
    if m and m in by_mac and not _is_lent_mac(m):
        return by_mac[m]
    card = by_ip.get(ip or "")
    if card and time.time() - float(card.get("seen") or 0) < IP_TTL_S:
        return card
    return None


def _label_only(card: dict) -> bool:
    """Every service heard from the device names only itself (see mdns_parse._MDNS_LABEL_ONLY): the remembered name is a label, not the name of the device."""
    services = set(card.get("services") or ())
    return bool(services) and services <= mdns_parse._MDNS_LABEL_ONLY


def as_scan_info(card: dict | None) -> dict:
    """The remembered card in the format of the scan_info fields (only the fields present)."""
    if not card:
        return {}
    fields = (("name", "mdns_name"), ("model", "mdns_model"), ("manufacturer", "mdns_manufacturer"))
    out = {dst: card[src] for src, dst in fields if card.get(src) and not (src == "name" and _label_only(card))}
    if card.get("services"):
        out["mdns_services"] = ", ".join(card["services"])[:200]
    return out


def start(state, lent_counts=None) -> None:
    """From the lifespan: loads the memory and starts listening (if zeroconf is missing only the memory remains)."""
    global _task, _mac_for_ip, _at_several_addresses, _lent_counts
    _load()

    def arp() -> dict:
        return state._view.cache[1] if getattr(getattr(state, "_view", None), "cache", None) else {}

    def mac_for_ip(ip: str):
        m = (arp().get(ip) or {}).get("mac")
        return str(m).lower() if m else None
    _mac_for_ip = mac_for_ip
    _at_several_addresses = lambda mac: [str((h or {}).get("mac")).lower() for h in arp().values()].count(mac) > 1  # noqa: E731  (a repeater lends its address to its clients)
    if lent_counts is not None:
        _lent_counts = lent_counts
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        logger.warning("zeroconf non installato: ascolto mDNS continuo non attivo")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_listen())


def _load() -> None:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        by_mac.update(data.get("by_mac") or {})
        by_ip.update(data.get("by_ip") or {})
    except (OSError, ValueError):
        pass


async def _listen() -> None:
    """Always-on DNS-SD browser: discovers the service types and browses each type; every instance seen is recorded."""
    browsing = Browsing.open(_remember, 3000)
    try:
        browsing.start()
        logger.info("Ascolto mDNS continuo avviato")
        while True:
            await asyncio.sleep(60)
            _housekeeping()
            if _dirty:
                await asyncio.to_thread(_save)
    finally:
        await browsing.close()
        if _dirty:
            _save()


def _remember(reading: tuple) -> None:
    short, instance, address, txt = reading
    record(address, short, instance, txt)


def _save() -> None:
    global _dirty
    _dirty = False
    snapshot = {"by_mac": dict(by_mac), "by_ip": dict(by_ip)}      # a copy made in one step: the loop may change the dictionaries while a worker thread serialises them
    try:
        write_atomic(STORE_PATH, lambda f: json.dump(snapshot, f, ensure_ascii=False), ".mdns-", folder=STORE_PATH.parent)
    except (OSError, ValueError, RuntimeError):
        logger.warning("Memoria mDNS non salvata", exc_info=True)      # never stop the listener for a failed save


def _housekeeping() -> None:
    """Ties to the MAC the cards kept by IP (as soon as ARP knows it) and discards the old ones."""
    global _dirty
    now = time.time()
    for ip, card in list(by_ip.items()):
        mac = _own_mac(ip)
        if mac:
            old = by_mac.get(mac)
            if not old or float(card.get("seen") or 0) >= float(old.get("seen") or 0):
                by_mac[mac] = card
            del by_ip[ip]
            _dirty = True
        elif now - float(card.get("seen") or 0) > IP_TTL_S:
            del by_ip[ip]
            _dirty = True


async def stop() -> None:
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _task
