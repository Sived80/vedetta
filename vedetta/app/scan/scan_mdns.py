"""scan_mdns: moved out of scanner.py (see tools/split_module.py)."""
import asyncio
from .scan_common import is_valid_ipv4
from ..applog import logger
import re
import struct
from ..formatters import truncate_name
from .mdns_parse import _MDNS_MANUFACTURER_KEYS, _MDNS_META_TYPE, _MDNS_MODEL_KEYS, _MDNS_NAME_KEYS, _MDNS_SLUG_RE, _MDNS_USER_NAMED, _props_to_txt, parse_mdns_txt  # noqa: F401
from . import mdns_listener
from .mdns_browsing import Browsing


# Model and manufacturer announced in the mDNS TXT records, per IP: {"model", "manufacturer"}.
# Keys by priority: "model" (_device-info: MacBookPro18,1, iPhone15,2), "am" (AirPlay:
# AppleTV6,2), "md" (Chromecast/HomeKit). It is filled at every mdns_scan; a device that stays silent keeps
# its last known value (the network is a home LAN: a few dozen entries).
mdns_meta: dict[str, dict] = {}


_MDNS_BUDGET = 6.0     # total seconds for the whole LAN (as with avahi-browse)


_MDNS_TYPES_WINDOW = 3.5  # after this time no new service types are searched for


_MDNS_INFO_TIMEOUT = 3000  # ms for the SRV/TXT/A request of a single instance


async def mdns_scan() -> dict[str, str]:
    """Real names via mDNS (Shelly, ESPHome, Home Assistant, Chromecast,
    Apple devices...) with the zeroconf library: no avahi daemon, so it
    also runs where there is none (Home Assistant add-on). A single passive
    browse covers the whole LAN."""
    found: list[tuple[str, str, str, str]] = []
    if await _browse_into(found):
        return {}
    best, seen_meta = _best_names(found)
    _store_meta(seen_meta)
    try:   # the names seen are remembered per MAC (a sleeping phone does not lose them)
        mdns_listener.remember_scan(found)
    except Exception:
        logger.exception("Memoria mDNS: salvataggio dalla scansione fallito")
    return {ip: truncate_name(v[1]) for ip, v in best.items()}


async def _browse_into(found: list) -> bool:
    """Runs the browse and fills `found`. True when the scan must stop and give no names (library missing, or it failed with nothing collected)."""
    try:
        await asyncio.wait_for(_mdns_browse(found), timeout=_MDNS_BUDGET)
    except asyncio.TimeoutError:
        pass
    except ImportError:
        logger.warning("Libreria zeroconf non installata: scansione mDNS saltata")
        return True
    except Exception as exc:
        logger.warning("Scansione mDNS fallita: %r", exc)
        if not found:
            return True
    return False


async def _mdns_browse(found: list[tuple[str, str, str, str]]) -> None:
    """DNS-SD browsing with zeroconf: the _services._dns-sd._udp meta-query discovers the
    service TYPES present on the LAN, then each type is browsed and each instance
    resolved (SRV+TXT+A). Fills `found` with (type, instance, ip, txt) as it goes:
    if the budget runs out the results already collected remain."""
    browsing = Browsing.open(found.append, _MDNS_INFO_TIMEOUT, _MDNS_TYPES_WINDOW)
    try:
        browsing.start()
        # Full window: exiting early on "quiet" made us lose slow devices
        # (tested on a LAN: 9 names out of 9 with the full window, 6-8 with early exit).
        await asyncio.sleep(_MDNS_BUDGET - 0.5)
        if browsing.tasks:
            await asyncio.wait(set(browsing.tasks), timeout=0.4)
    finally:
        await browsing.close()


def _best_names(found: list) -> tuple[dict[str, tuple[int, str]], dict[str, dict]]:
    """Best (score, name) per address, and what was seen per address (service types, model, manufacturer)."""
    best: dict[str, tuple[int, str]] = {}
    seen_meta: dict[str, dict] = {}
    for stype, name, address, txt in found:
        if not is_valid_ipv4(address):
            continue
        score, value = (2 if stype in _MDNS_USER_NAMED else 1), name
        seen_meta.setdefault(address, {}).setdefault("services", set()).add(stype)
        for field, got in parse_mdns_txt(txt).items():
            seen_meta.setdefault(address, {}).setdefault(field, got)
        named = _txt_name(txt)
        if named:
            score, value = named
        if address not in best or score > best[address][0]:
            best[address] = (score, value)
    return best, seen_meta


def _txt_name(txt: str) -> tuple[int, str] | None:
    """(score, name) from the first name key of the TXT record that holds a user-chosen value, else None."""
    for key, key_score in _MDNS_NAME_KEYS:
        m = re.search(key + r'=([^"]*)', txt)
        # A value like "5c53de3b-esphome" is an automatically generated id
        # (e.g. from a technical add-on), not a user-chosen name: it must be ignored
        # even if it appears under the "friendly_name" key.
        if m and m.group(1) and not _MDNS_SLUG_RE.match(m.group(1)):
            return key_score, m.group(1)
    return None


def _store_meta(seen_meta: dict[str, dict]) -> None:
    """Merges what was seen into the module memory `mdns_meta` (service types become sorted lists)."""
    for ip, meta in seen_meta.items():
        if "services" in meta:
            meta["services"] = sorted(meta["services"])
        mdns_meta.setdefault(ip, {}).update(meta)


class _PtrProtocol(asyncio.DatagramProtocol):
    def __init__(self, future: asyncio.Future) -> None:
        self.future = future

    def datagram_received(self, data, addr) -> None:
        if not self.future.done():
            self.future.set_result(data)


async def resolve_mdns_name(ip: str) -> str | None:
    """Active, direct mDNS query on a single address ("who has this IP?"),
    unlike mdns_scan() which is passive and only listens to whoever announces
    Bonjour/DNS-SD services. An Android/iOS phone or a Windows PC often
    publishes only its own .local hostname without announcing any service:
    the passive scan misses them entirely, this one finds them. Verified that
    this is exactly how Advanced IP Scanner finds names like "MSI", "Android",
    "iPhone-di-Caio" that we were completely missing before.

    Unicast PTR query sent to ip:5353 (hand-built packet, no
    daemon needed); the device replies to the source address."""
    if not is_valid_ipv4(ip):
        return None
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _PtrProtocol(future), remote_addr=(ip, 5353),
        )
    except OSError:
        return None
    try:
        transport.sendto(_build_ptr_query(ip))
        data = await asyncio.wait_for(future, timeout=1.5)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        transport.close()
    name = _parse_ptr_answer(data)
    if not name:
        return None
    name = name.rstrip(".")
    name = name.removesuffix(".local")
    return truncate_name(name) or None


def _build_ptr_query(ip: str) -> bytes:
    """DNS packet: a PTR question for d.c.b.a.in-addr.arpa (class IN, QU/
    unicast-response bit set as in direct 'legacy' mDNS queries)."""
    qname = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in qname.split("."))
    return header + labels + b"\x00" + struct.pack(">HH", 12, 0x8001)


def _parse_ptr_answer(data: bytes) -> str | None:
    """First PTR record in the answer (or additional) section of a DNS response."""
    if len(data) < 12:
        return None
    _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    pos = 12
    try:
        for _ in range(qd):
            _, pos = _read_dns_name(data, pos)
            pos += 4
        for _ in range(an + ns + ar):
            _, pos = _read_dns_name(data, pos)
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos: pos + 10])
            pos += 10
            if rtype == 12:
                name, _ = _read_dns_name(data, pos)
                return name
            pos += rdlen
    except (ValueError, struct.error):
        return None
    return None


def _read_dns_name(data: bytes, pos: int) -> tuple[str, int]:
    """DNS name (with compression pointers) at `pos`: (name, position after)."""
    labels, end, jumped, hops = [], pos, False, 0
    while True:
        if pos >= len(data) or hops > 20:
            raise ValueError("nome DNS non valido")
        length = data[pos]
        if length == 0:
            pos += 1
            break
        if length & 0xC0 == 0xC0:
            ptr = ((length & 0x3F) << 8) | data[pos + 1]
            if not jumped:
                end = pos + 2
            pos, jumped, hops = ptr, True, hops + 1
            continue
        labels.append(data[pos + 1: pos + 1 + length].decode("utf-8", "replace"))
        pos += 1 + length
    return ".".join(labels), (end if jumped else pos)


async def resolve_names(ips: list[str], passive_names: dict[str, str] | None = None) -> dict[str, str]:
    """mDNS names for a list of addresses: starts from the passive scan (a
    single call for the whole network, better names for devices that publish them as
    friendly_name/location_name) and completes with a targeted active query only
    on the addresses left without a name - in parallel, they cost as much as the
    slowest of the individual timeouts, not the sum."""
    names = dict(passive_names) if passive_names is not None else await mdns_scan()
    missing = [ip for ip in ips if ip not in names]
    if missing:
        resolved = await asyncio.gather(*(resolve_mdns_name(ip) for ip in missing))
        for ip, name in zip(missing, resolved):
            if name:
                names[ip] = name
    return names
