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


from ..paths import DATA_DIR as CONFIG_DIR
import contextlib

logger = logging.getLogger("dashboard")

STORE_PATH = CONFIG_DIR / "dhcp_seen.json"
_DHCP_REQUEST_TYPES = {1, 3}  # DISCOVER, REQUEST
_MAGIC_COOKIE = b"\x63\x82\x53\x63"

# mac (lowercase, colon-separated) -> {"hostname", "prl", "vendor_class", "seen"}
seen: dict[str, dict] = {}
# DHCP server IP (option 54 in client requests) -> last time seen
servers: dict[str, float] = {}


def _save() -> None:
    try:
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except OSError:
        pass


def _dotted(value: bytes) -> str:
    return ".".join(str(b) for b in value)


def parse(packet: bytes) -> tuple[str, dict] | None:
    """Extracts the MAC and useful options from a client BOOTP/DHCP packet."""
    if len(packet) < 241 or packet[0] != 1 or packet[236:240] != _MAGIC_COOKIE:
        return None
    mac = ":".join(f"{b:02x}" for b in packet[28:34])
    msg_type, info, requested = _read_options(packet)
    if msg_type not in _DHCP_REQUEST_TYPES:
        return None
    # The address this client (chaddr, its own MAC even behind a repeater) says it uses: ciaddr when it already has one (renewal), else
    # the address it asks for in a REQUEST. A DISCOVER's option 50 is only a hint of the last address, so it is not taken as evidence.
    ciaddr = _dotted(packet[12:16])
    if ciaddr != "0.0.0.0":
        info["ip"], info["ip_from"] = ciaddr, "ciaddr"
    elif requested and msg_type == 3:
        info["ip"], info["ip_from"] = requested, "requested"
    return mac, info


def _read_options(packet: bytes) -> tuple[int | None, dict, str | None]:
    """(message type, options kept, address asked for) from the options of a client packet; a broken length ends the reading."""
    msg_type, requested, info = None, None, {}
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
        elif code == 50 and len(value) == 4:
            requested = _dotted(value)
        else:
            _store_option(info, code, value)
    return msg_type, info, requested


def _store_option(info: dict, code: int, value: bytes) -> None:
    """The options kept as they are: host name, parameter request list, vendor class, client identifier, server identifier."""
    if code == 12:
        info["hostname"] = _text(value)
    elif code == 55:
        info["prl"] = ",".join(str(b) for b in value)
    elif code == 60:
        info["vendor_class"] = _text(value)
    elif code == 61 and value:
        info["client_id"] = value.hex()        # client identifier (RFC 2132, RFC 4361): type byte + id, kept as hex
    elif code == 54 and len(value) == 4:
        info["server_id"] = _dotted(value)


def _text(value: bytes) -> str:
    return value.decode("utf-8", "ignore").strip("\x00 ")


def _merge_entry(previous: dict, info: dict) -> dict:
    """The memory entry after a packet: the old one overwritten by the fields of the packet that are not empty (a request without a name,
    common in renewals, does not erase the name seen previously), with the time of the packet and, if the packet carried an address, the
    time of that address (a DISCOVER keeps the old address but does not renew it)."""
    entry = {**previous, **{k: v for k, v in info.items() if v}, "seen": int(time.time())}
    if info.get("ip"):
        entry["ip_ts"] = entry["seen"]
    return entry


def _kept_fields(entry: dict) -> dict:
    """The fields of an entry that count when deciding whether it changed (not the times)."""
    return {k: v for k, v in entry.items() if k not in ("seen", "ip_ts")}


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
        entry = _merge_entry(previous, info)
        changed = _kept_fields(entry) != _kept_fields(previous)
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


def _load() -> None:
    with contextlib.suppress(OSError, ValueError):
        seen.update(json.loads(STORE_PATH.read_text(encoding="utf-8")))


# ---- classification ----

def is_private_mac(mac: str | None) -> bool:
    """U/L bit (second least significant bit of the first byte) = locally
    assigned address: it is the "private MAC" of iOS/Android/Windows."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (AttributeError, ValueError):
        return False


# What a system asks for in option 55 tells which system it is: the first family whose options are ALL asked for (after the Apple rule, which is the most specific).
_FAMILIES_BY_OPTIONS = (("windows", (249, 252)), ("android", (26, 28, 51, 58)), ("linux", (28, 12)))


def _os_family(prl: str | None, vendor_class: str | None) -> str | None:
    return _family_from_vendor_class((vendor_class or "").lower()) or _family_from_request_list(prl)


def _family_from_vendor_class(vc: str) -> str | None:
    """The vendor class (option 60, lower case) names the system when it is one of the well known ones."""
    # ChromeOS asks for the same options as iOS: its own vendor class tells it apart (it is a laptop, not an iPhone)
    if "chromeos" in vc.replace(" ", ""):
        return "chromeos"
    if vc.startswith("android-dhcp"):
        return "android"
    if vc.startswith("msft"):
        return "windows"
    if vc.startswith(("dhcpcd", "udhcp")):
        return "linux"
    return None


def _family_from_request_list(prl: str | None) -> str | None:
    """The parameter request list (option 55) is a fingerprint of the system."""
    if not prl:
        return None
    opts = [int(x) for x in prl.split(",") if x.isdigit()]
    apple = _apple_family(opts)
    if apple:
        return apple
    return next((family for family, codes in _FAMILIES_BY_OPTIONS if all(c in opts for c in codes)), None)


def _apple_family(opts: list) -> str | None:
    """iOS and macOS share the base fingerprint (1, 121, 3, ... 252): macOS adds 95, 44, 46."""
    if opts[:3] != [1, 121, 3] or 252 not in opts:
        return None
    return "macos" if 95 in opts or 44 in opts else "ios"


def os_family(mac: str | None) -> str | None:
    """Operating system family inferred from the MAC's DHCP fingerprint, if seen."""
    entry = seen.get((mac or "").lower())
    return _os_family(entry.get("prl"), entry.get("vendor_class")) if entry else None


_DESKTOP_FAMILIES = ("windows", "macos", "linux", "chromeos")


def mobile_score(mac: str | None, name_is_mobile: bool, has_ports: bool | None) -> tuple[int, str | None]:
    """DHCP part of the "mobile" score (the other evidence - mDNS model, presence,
    network battery - is added in identity.mobile_assess). "Is it a phone/tablet" score, with the main clue for the
    tooltip. >= 3 counts as mobile. Rule: the iOS fingerprint and a phone-like name
    are enough on their own; the Android fingerprint is not (it also applies to TVs) and must be
    confirmed, usually by the private MAC; the private MAC and the absence of listening
    ports are weak clues and are not enough on their own."""
    entry = seen.get((mac or "").lower())
    clues = [(3, "nome")] if name_is_mobile else []
    if entry:
        clues += _entry_clues(entry)
    if is_private_mac(mac):
        clues.append((1, "MAC privato"))
    score, reason = 0, None
    for points, why in clues:
        score += points
        reason = reason or why  # the first clue that has a reason is the main one
    return score, reason


def _entry_clues(entry: dict) -> list[tuple[int, str | None]]:
    """The clues of what the memory knows about a MAC: first the fingerprint, then the host name."""
    clues = (_family_clue(_os_family(entry.get("prl"), entry.get("vendor_class"))), _hostname_clue(entry.get("hostname")))
    return [c for c in clues if c]


def _family_clue(family: str | None) -> tuple[int, str | None] | None:
    """(points, reason) that the DHCP fingerprint gives to the "mobile" score, None if it gives nothing. iOS/iPadOS is always a phone or a tablet: the
    fingerprint is enough. Android also runs on TVs, set-top boxes and projectors: on its own it is not enough, a second clue is needed (usually the
    private MAC, which phones use and TVs do not). A desktop system lowers the score and is not a reason."""
    if family == "ios":
        return 3, "impronta DHCP (ios)"
    if family == "android":
        return 2, "impronta DHCP (android)"
    if family in _DESKTOP_FAMILIES:
        return -2, None
    return None


def _hostname_clue(hostname: str | None) -> tuple[int, str | None] | None:
    """(points, reason) that the host name sent by the client gives to the "mobile" score, None if it gives nothing."""
    host = (hostname or "").lower()
    if host.startswith(("iphone", "ipad")):
        return 3, "nome DHCP"
    if host.startswith("android-"):
        return 2, "nome DHCP"
    return None
