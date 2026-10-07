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
from pathlib import Path

from .. import paths
from ..applog import logger

STORE_PATH = paths.data_path("mdns_seen.json")
IP_TTL_S = 14 * 86400
_NAME_STRONG = 3   # score of a user-chosen name (friendly_name / service with a user name)

by_mac: dict[str, dict] = {}   # lowercase mac -> {"name", "score", "model", "manufacturer", "services", "ip", "seen"}
by_ip: dict[str, dict] = {}    # ip -> same card, until the MAC is known
_mac_for_ip = lambda ip: None  # noqa: E731  (set by start)
_task: asyncio.Task | None = None
_dirty = False


def _load() -> None:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        by_mac.update(data.get("by_mac") or {})
        by_ip.update(data.get("by_ip") or {})
    except (OSError, ValueError):
        pass


def _save() -> None:
    global _dirty
    _dirty = False
    try:
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"by_mac": by_mac, "by_ip": by_ip}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except OSError:
        pass


def score_name(stype: str, instance: str, txt: str) -> tuple[int, str]:
    """(score, name) of an announcement: same choice as the scan (TXT keys, services with a user name)."""
    from . import scanner
    score, value = (2 if stype in scanner._MDNS_USER_NAMED else 1), instance
    for key, key_score in scanner._MDNS_NAME_KEYS:
        m = re.search(key + r'=([^"]*)', txt)
        if m and m.group(1) and not scanner._MDNS_SLUG_RE.match(m.group(1)):
            return key_score, m.group(1)
    return score, value


def record(ip: str, stype: str, instance: str, txt: str, now: float | None = None) -> None:
    """Remembers an announcement (called both by continuous listening and by the scan)."""
    global _dirty
    from . import scanner
    if not scanner.is_valid_ipv4(ip):
        return
    now = time.time() if now is None else now
    score, name = score_name(stype, instance, txt)
    meta = scanner.parse_mdns_txt(txt)
    mac = _mac_for_ip(ip)
    card = by_mac.get(mac) if mac else by_ip.get(ip)
    card = dict(card or {})
    services = set(card.get("services") or []) | {stype}
    # a better name replaces the old one; on equal score the most recent wins
    if score >= int(card.get("score") or 0):
        card.update(name=scanner.truncate_name(name), score=score)
    for key in ("model", "manufacturer"):
        if meta.get(key):
            card[key] = meta[key]
    card.update(services=sorted(services), ip=ip, seen=now)
    if mac:
        by_mac[mac] = card
        by_ip.pop(ip, None)
    else:
        by_ip[ip] = card
    _dirty = True


def remember_scan(found: list[tuple[str, str, str, str]]) -> None:
    """Announcements collected by an mDNS scan (type, instance, ip, txt)."""
    for stype, instance, ip, txt in found:
        record(ip, stype, instance, txt)


def lookup(mac, ip: str | None = None) -> dict | None:
    """Card remembered for that MAC or, if missing, for that IP (recent). None if never seen."""
    m = str(mac or "").strip().lower().replace("-", ":")
    if m and m in by_mac:
        return by_mac[m]
    card = by_ip.get(ip or "")
    if card and time.time() - float(card.get("seen") or 0) < IP_TTL_S:
        return card
    return None


def as_scan_info(card: dict | None) -> dict:
    """The remembered card in the format of the scan_info fields (only the fields present)."""
    if not card:
        return {}
    out = {}
    for src, dst in (("name", "mdns_name"), ("model", "mdns_model"), ("manufacturer", "mdns_manufacturer")):
        if card.get(src):
            out[dst] = card[src]
    if card.get("services"):
        out["mdns_services"] = ", ".join(card["services"])[:200]
    return out


def _housekeeping() -> None:
    """Ties to the MAC the cards kept by IP (as soon as ARP knows it) and discards the old ones."""
    global _dirty
    now = time.time()
    for ip, card in list(by_ip.items()):
        mac = _mac_for_ip(ip)
        if mac:
            old = by_mac.get(mac)
            if not old or float(card.get("seen") or 0) >= float(old.get("seen") or 0):
                by_mac[mac] = card
            del by_ip[ip]
            _dirty = True
        elif now - float(card.get("seen") or 0) > IP_TTL_S:
            del by_ip[ip]
            _dirty = True


async def _listen() -> None:
    """Always-on DNS-SD browser: discovers the service types and browses each type; every instance seen is recorded."""
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf
    from . import scanner

    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    browsers: list = []
    types: set[str] = set()
    tasks: set[asyncio.Task] = set()

    async def read_instance(stype: str, name: str) -> None:
        info = AsyncServiceInfo(stype, name)
        try:
            if not await info.async_request(azc.zeroconf, 3000):
                return
        except Exception:
            return
        suffix = "." + stype
        instance = name[: -len(suffix)] if name.endswith(suffix) else name
        txt = scanner._props_to_txt(info.properties)
        short = stype[: -len(".local.")] if stype.endswith(".local.") else stype
        for address in info.parsed_addresses(IPVersion.V4Only):
            record(address, short, instance, txt)

    def on_instance(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        task = asyncio.ensure_future(read_instance(service_type, name))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def on_type(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Removed or name in types:
            return
        types.add(name)
        browsers.append(AsyncServiceBrowser(azc.zeroconf, name, handlers=[on_instance]))

    try:
        browsers.append(AsyncServiceBrowser(azc.zeroconf, scanner._MDNS_META_TYPE, handlers=[on_type]))
        logger.info("Ascolto mDNS continuo avviato")
        while True:
            await asyncio.sleep(60)
            _housekeeping()
            if _dirty:
                await asyncio.to_thread(_save)
    except asyncio.CancelledError:
        raise
    finally:
        for b in browsers:
            try:
                await b.async_cancel()
            except Exception:
                pass
        for t in list(tasks):
            t.cancel()
        try:
            await azc.async_close()
        except Exception:
            pass
        if _dirty:
            _save()


def start(state) -> None:
    """From the lifespan: loads the memory and starts listening (if zeroconf is missing only the memory remains)."""
    global _task, _mac_for_ip
    _load()

    def mac_for_ip(ip: str):
        arp = state._arp[1] if getattr(state, "_arp", None) else {}
        host = arp.get(ip)
        m = (host or {}).get("mac")
        return str(m).lower() if m else None
    _mac_for_ip = mac_for_ip
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        logger.warning("zeroconf non installato: ascolto mDNS continuo non attivo")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_listen())


async def stop() -> None:
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
