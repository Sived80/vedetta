"""Passive DHCP listening: clients (phones included) broadcast their own name
(option 12), the list of requested parameters (option 55, which has a
characteristic order for each operating system - the principle behind Fingerbank
fingerprints) and the vendor class (option 60) when they join the network or
ask for a lease. Nothing is sent: we only read what passes by in broadcast on
the segment."""
import asyncio
import json
import logging
import socket
import time


from .paths import DATA_DIR as CONFIG_DIR

logger = logging.getLogger("dashboard")

STORE_PATH = CONFIG_DIR / "dhcp_seen.json"
_DHCP_REQUEST_TYPES = {1, 3}  # DISCOVER, REQUEST
_MAGIC_COOKIE = b"\x63\x82\x53\x63"

# mac (lowercase, colon-separated) -> {"hostname", "prl", "vendor_class", "seen"}
seen: dict[str, dict] = {}
# DHCP server IP (option 54 in client requests) -> last time seen
servers: dict[str, float] = {}


def _load() -> None:
    try:
        seen.update(json.loads(STORE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _save() -> None:
    try:
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except OSError:
        pass


def parse(packet: bytes) -> tuple[str, dict] | None:
    """Extracts the MAC and useful options from a client BOOTP/DHCP packet."""
    if len(packet) < 241 or packet[0] != 1 or packet[236:240] != _MAGIC_COOKIE:
        return None
    mac = ":".join(f"{b:02x}" for b in packet[28:34])
    info: dict = {}
    msg_type = None
    i = 240
    while i < len(packet):
        code = packet[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(packet):
            break
        length = packet[i + 1]
        value = packet[i + 2:i + 2 + length]
        i += 2 + length
        if code == 53 and value:
            msg_type = value[0]
        elif code == 12:
            info["hostname"] = value.decode("utf-8", "ignore").strip("\x00 ")
        elif code == 55:
            info["prl"] = ",".join(str(b) for b in value)
        elif code == 60:
            info["vendor_class"] = value.decode("utf-8", "ignore").strip("\x00 ")
        elif code == 54 and len(value) == 4:
            info["server_id"] = ".".join(str(b) for b in value)
    if msg_type not in _DHCP_REQUEST_TYPES:
        return None
    return mac, info


class _Listener(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr) -> None:
        parsed = parse(data)
        if not parsed:
            return
        mac, info = parsed
        server = info.pop("server_id", None)
        if server:
            servers[server] = time.time()
        previous = seen.get(mac, {})
        # A request without a name (common in renewals) does not erase the
        # name seen previously.
        entry = {**previous, **{k: v for k, v in info.items() if v}, "seen": int(time.time())}
        changed = {k: v for k, v in entry.items() if k != "seen"} != {k: v for k, v in previous.items() if k != "seen"}
        seen[mac] = entry
        if changed:
            logger.info("DHCP: %s hostname=%s prl=%s classe=%s", mac, entry.get("hostname") or "-",
                        entry.get("prl") or "-", entry.get("vendor_class") or "-")
            _save()


async def start() -> asyncio.BaseTransport | None:
    _load()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 67))
        sock.setblocking(False)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(_Listener, sock=sock)
    except OSError as exc:
        sock.close()
        logger.warning("Ascolto DHCP non attivo (porta 67): %s", exc)
        return None
    logger.info("Ascolto DHCP passivo attivo (porta 67)")
    return transport


# ---- classification ----

def is_private_mac(mac: str | None) -> bool:
    """U/L bit (second least significant bit of the first byte) = locally
    assigned address: it is the "private MAC" of iOS/Android/Windows."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (AttributeError, ValueError):
        return False


def _os_family(prl: str | None, vendor_class: str | None) -> str | None:
    vc = (vendor_class or "").lower()
    if vc.startswith("android-dhcp"):
        return "android"
    if vc.startswith("msft"):
        return "windows"
    if vc.startswith(("dhcpcd", "udhcp")):
        return "linux"
    if not prl:
        return None
    opts = [int(x) for x in prl.split(",") if x.isdigit()]
    if opts[:3] == [1, 121, 3] and 252 in opts:
        # Same base fingerprint for iOS and macOS: macOS adds 95, 44, 46.
        return "macos" if 95 in opts or 44 in opts else "ios"
    if 249 in opts and 252 in opts:
        return "windows"
    if 26 in opts and 28 in opts and 51 in opts and 58 in opts:
        return "android"
    if 28 in opts and 12 in opts:
        return "linux"
    return None


def os_family(mac: str | None) -> str | None:
    """Operating system family inferred from the MAC's DHCP fingerprint, if seen."""
    entry = seen.get((mac or "").lower())
    return _os_family(entry.get("prl"), entry.get("vendor_class")) if entry else None


def mobile_score(mac: str | None, name_is_mobile: bool, has_ports: bool | None) -> tuple[int, str | None]:
    """DHCP part of the "mobile" score (the other evidence - mDNS model, presence,
    network battery - is added in identity.mobile_assess). "Is it a phone/tablet" score, with the main clue for the
    tooltip. >= 3 counts as mobile. Rule: the iOS fingerprint and a phone-like name
    are enough on their own; the Android fingerprint is not (it also applies to TVs) and must be
    confirmed, usually by the private MAC; the private MAC and the absence of listening
    ports are weak clues and are not enough on their own."""
    entry = seen.get((mac or "").lower())
    score, reason = 0, None
    if name_is_mobile:
        score, reason = score + 3, "nome"
    if entry:
        family = _os_family(entry.get("prl"), entry.get("vendor_class"))
        # iOS/iPadOS is always a phone or a tablet: the fingerprint is enough. Android also runs
        # on TVs, set-top boxes and projectors: on its own it is not enough, a second
        # clue is needed (usually the private MAC, which phones use and TVs do not).
        if family == "ios":
            score, reason = score + 3, reason or "impronta DHCP (ios)"
        elif family == "android":
            score, reason = score + 2, reason or "impronta DHCP (android)"
        elif family in ("windows", "macos", "linux"):
            score -= 2
        host = (entry.get("hostname") or "").lower()
        if host.startswith("iphone") or host.startswith("ipad"):
            score, reason = score + 3, reason or "nome DHCP"
        elif host.startswith("android-"):
            score, reason = score + 2, reason or "nome DHCP"
    if is_private_mac(mac):
        score, reason = score + 1, reason or "MAC privato"
    return score, reason
