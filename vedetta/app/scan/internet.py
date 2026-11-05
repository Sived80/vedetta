"""Outbound internet connectivity: public IP, double NAT, provider CGNAT.

  public IP    standard DNS query to the OpenDNS resolver for myip.opendns.com: the
               answer is the address the query comes from (no web API)
  path         nmap traceroute (--traceroute) to 1.1.1.1: the first hops
  double NAT   the router itself, asked over UPnP (upnp_wan.py), says its internet side has a private
               address: there is another router (e.g. the provider's modem) in front of yours. Without
               that answer, two or more private hops before the first public one only make it
               "possible": a router inside the network (VLANs) gives two private hops without NAT
  CGNAT        a hop in 100.64.0.0/10 (RFC 6598) before the first public one: the
               provider shares the public IP among multiple customers"""
import asyncio
import ipaddress
import secrets
import struct
import time
import xml.etree.ElementTree as ET

from .. import external
from . import upnp_wan
from ..applog import logger

OPENDNS = "208.67.222.222"
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def build_query(qid: int, name: str, qtype: int = 1) -> bytes:
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + bytes([0])
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", qtype, 1)


def parse_a_answer(data: bytes, qid: int) -> str | None:
    """First A record of the answer, None if missing or invalid."""
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != qid or not data[2] & 0x80:
        return None
    qd, an = struct.unpack(">HH", data[4:8])
    pos = 12
    for _ in range(qd):
        pos = _skip_name(data, pos) + 4
    for _ in range(an):
        pos = _skip_name(data, pos)
        if pos + 10 > len(data):
            return None
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        if rtype == 1 and rdlen == 4:
            return ".".join(str(b) for b in data[pos:pos + 4])
        pos += rdlen
    return None


def _skip_name(data: bytes, pos: int) -> int:
    while pos < len(data):
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:
            return pos + 2
        pos += 1 + length
    return pos


class _Reply(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.data = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr) -> None:
        if not self.data.done():
            self.data.set_result(data)


async def public_ip(timeout: float = 3.0) -> str | None:
    loop = asyncio.get_running_loop()
    qid = secrets.randbelow(65535) + 1      # not guessable: a guessed id lets someone else answer in place of the resolver
    try:
        transport, proto = await loop.create_datagram_endpoint(_Reply, remote_addr=(OPENDNS, 53))
    except OSError:
        return None
    try:
        transport.sendto(build_query(qid, "myip.opendns.com"))
        data = await asyncio.wait_for(proto.data, timeout)
        return parse_a_answer(data, qid)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        transport.close()


def parse_trace(xml_text: str) -> list[str]:
    try:
        root = ET.fromstring(xml_text)  # noqa: S314  the XML of nmap, written by nmap itself
    except ET.ParseError:
        return []
    hops = []
    for hop in root.findall("host/trace/hop"):
        try:
            hops.append((int(hop.get("ttl", "0")), hop.get("ipaddr")))
        except ValueError:
            continue
    return [ip for _, ip in sorted(hops) if ip]


def classify(hops: list[str], wan: str | None = None) -> dict:
    """Hops up to the first public one: how many are private, whether CGNAT is present. `wan` = the internet-side address the
    router declared over UPnP, when it answered: it decides the double NAT; without it two private hops are only "possible"."""
    private, cgnat = [], False
    for ip in hops:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr in _CGNAT:
            cgnat = True
            continue
        if addr.is_private:
            private.append(ip)
            continue
        break
    side = _wan_side(wan)
    return {"private_hops": private, "double_nat": side == "private", "maybe_double_nat": side is None and len(private) >= 2,
            "cgnat": cgnat or side == "cgnat", "wan_checked": side is not None}


def _wan_side(wan: str | None) -> str | None:
    """What the WAN address of the router says: "private", "cgnat", "public", or None when there is no usable answer."""
    try:
        addr = ipaddress.ip_address(wan or "")
    except ValueError:
        return None
    if addr.version != 4 or addr.is_unspecified or addr.is_loopback:
        return None
    return "cgnat" if addr in _CGNAT else "private" if addr.is_private else "public"


async def _nothing():
    return None


async def check() -> dict:
    """Only what the add-on options leave on (external.py): a function that is off sends nothing and its part of the result stays empty."""
    from .scanner import _LIGHT_NMAP_SEMAPHORE, _run_nmap
    want_ip, want_path = external.public_ip_enabled(), external.path_enabled()
    trace_xml, ip = await asyncio.gather(
        _run_nmap(["-sn", "-Pn", "--traceroute", "--max-retries", "1", "--host-timeout", "20s", external.path_target()],
                  semaphore=_LIGHT_NMAP_SEMAPHORE) if want_path else _nothing(),
        public_ip() if want_ip else _nothing(), return_exceptions=True)
    hops = parse_trace(trace_xml) if isinstance(trace_xml, str) else []
    wan = await _router_wan(hops) if want_path else None
    result = {"public_ip": ip if isinstance(ip, str) else None, "hops": hops[:5], **classify(hops, wan), "ts": time.time(),
              "checks": {"public_ip": want_ip, "path": want_path}}
    _log(result)
    return result


def _log(result: dict) -> None:
    logger.info("Internet: IP pubblico %s, salti %s, doppio NAT %s, CGNAT %s", result["public_ip"] or "-", " > ".join(result["hops"]) or "-",
                "si" if result["double_nat"] else "forse" if result["maybe_double_nat"] else "no", "si" if result["cgnat"] else "no")


async def _router_wan(hops: list[str]) -> str | None:
    """The WAN address declared by the first hop (the router), only when two private hops leave the double NAT open."""
    if len(classify(hops)["private_hops"]) < 2:
        return None
    try:
        return await upnp_wan.wan_address(hops[0])
    except Exception as exc:  # noqa: BLE001  (the check of the way out must not fail for the router's UPnP)
        logger.info("UPnP del router non letto (%r)", exc)
        return None
