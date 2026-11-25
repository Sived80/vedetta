"""Outbound internet connectivity: public IP, double NAT, provider CGNAT.

  public IP    standard DNS query to the OpenDNS resolver for myip.opendns.com: the
               answer is the address the query comes from (no web API). Without an address,
               one more query to the same resolver, debug.opendns.com TXT, tells why: the real
               OpenDNS answers it with a "server <name>" line; an answer without it means that
               something on the way (router, DNS filter) answers port 53 in its place
               ("redirected"); no answer at all is "no_reply" (transient)
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
from ..networks import registry
from . import upnp_wan
from ..applog import logger

OPENDNS = "208.67.222.222"
DNS_TIMEOUT_S = 3.0
_TXT = 16
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def build_query(qid: int, name: str, qtype: int = 1) -> bytes:
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + bytes([0])
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", qtype, 1)


def parse_a_answer(data: bytes, qid: int) -> str | None:
    """First A record of the answer, None if missing or invalid."""
    for rtype, rdata in _records(data, qid) or ():
        if rtype == 1 and len(rdata) == 4:
            return ".".join(str(b) for b in rdata)
    return None


def parse_txt_answer(data: bytes, qid: int) -> list[str] | None:
    """The character strings of the TXT records of the answer, None when the packet is not a reply to this query. A cut record or string
    is dropped, never an error."""
    records = _records(data, qid)
    if records is None:
        return None
    texts = []
    for rtype, rdata in records:
        pos = 0
        while rtype == _TXT and pos < len(rdata) and pos + 1 + rdata[pos] <= len(rdata):
            texts.append(rdata[pos + 1:pos + 1 + rdata[pos]].decode("ascii", "replace"))
            pos += 1 + rdata[pos]
    return texts


def _records(data: bytes, qid: int) -> list[tuple[int, bytes]] | None:
    """(type, data) of each answer record, None when the packet is not a reply to this query. Bounded by the packet: a cut record ends the list."""
    if len(data) < 12 or struct.unpack(">H", data[:2])[0] != qid or not data[2] & 0x80:
        return None
    qd, an = struct.unpack(">HH", data[4:8])
    pos, out = 12, []
    for _ in range(qd):
        pos = _skip_name(data, pos) + 4
    for _ in range(an):
        pos = _skip_name(data, pos)
        if pos + 10 > len(data):
            break
        rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos:pos + 10])
        pos += 10
        if pos + rdlen > len(data):
            break
        out.append((rtype, data[pos:pos + rdlen]))
        pos += rdlen
    return out


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


async def _ask(name: str, qtype: int, parse, timeout: float | None):
    """One query to OpenDNS, the answer through `parse`; None without a reply."""
    loop = asyncio.get_running_loop()
    qid = secrets.randbelow(65535) + 1      # not guessable: a guessed id lets someone else answer in place of the resolver
    try:
        transport, proto = await loop.create_datagram_endpoint(_Reply, remote_addr=(OPENDNS, 53))
    except OSError:
        return None
    try:
        transport.sendto(build_query(qid, name, qtype))
        data = await asyncio.wait_for(proto.data, timeout or DNS_TIMEOUT_S)
        return parse(data, qid)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        transport.close()


async def public_ip(timeout: float | None = None) -> str | None:
    return await _ask("myip.opendns.com", 1, parse_a_answer, timeout)


async def opendns_answers(timeout: float | None = None) -> bool | None:
    """Whether the real OpenDNS answers: its debug.opendns.com TXT has a "server <name>" line. False = a reply without it (redirected),
    None = no reply. Only this yes/no leaves the function: the text carries the public address of the client and is never kept."""
    texts = await _ask("debug.opendns.com", _TXT, parse_txt_answer, timeout)
    return None if texts is None else any(t.startswith("server ") for t in texts)


async def _ip_status(ip: str | None) -> str:
    """ok / redirected / no_reply: the debug query goes out only when there is no address."""
    if ip:
        return "ok"
    return "redirected" if await opendns_answers() is False else "no_reply"


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


def classify(hops: list[str], wan: str | None = None, home: tuple = ()) -> dict:
    """Hops up to the first public one: how many are private, whether CGNAT is present. `wan` = the internet-side address the
    router declared over UPnP, when it answered: it decides the double NAT; without it two private steps are only "possible".
    `home` = the networks of the house (the main one and the written ones): the hops inside them count as one step (home_steps)."""
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
    return {"private_hops": private, "double_nat": side == "private", "maybe_double_nat": side is None and home_steps(private, home) >= 2,
            "cgnat": cgnat or side == "cgnat", "wan_checked": side is not None}


def home_steps(private: list[str], home: tuple) -> int:
    """The private hops as routers of the way out: those inside the networks of the house are one (a router between the VLANs of the
    house and the main router is no NAT of its own), each one outside them is one more."""
    inside = [ip for ip in private if any(ipaddress.ip_address(ip) in net for net in home)]
    return (1 if inside else 0) + len(private) - len(inside)


async def _home() -> tuple:
    """The confirmed networks of the house, the main one first; none when they cannot be read (the check of the way out goes on)."""
    try:
        scope = await registry.current()
    except Exception as exc:  # noqa: BLE001  (the check of the way out must not fail for the networks)
        logger.info("Reti di casa non lette per il doppio NAT (%r)", exc)
        return ()
    return tuple(n.cidr for n in scope.networks if n.state == "confirmed")


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


async def check(previous: dict | None = None) -> dict:
    """Only what the add-on options leave on (external.py): a function that is off sends nothing and its part of the result stays empty.
    `previous` = the last result, for the quick retry after a public IP without reply: only the public IP is asked again, the path is kept."""
    from .scanner import _LIGHT_NMAP_SEMAPHORE, _run_nmap
    want_ip, want_path = external.public_ip_enabled(), external.path_enabled()
    if previous is not None and want_ip:
        ip = await public_ip()
        result = {**previous, "public_ip": ip, "public_ip_status": await _ip_status(ip), "ts": time.time()}
        _log(result)
        return result
    trace_xml, ip = await asyncio.gather(
        _run_nmap(["-sn", "-Pn", "--traceroute", "--max-retries", "1", "--host-timeout", "20s", external.path_target()],
                  semaphore=_LIGHT_NMAP_SEMAPHORE) if want_path else _nothing(),
        public_ip() if want_ip else _nothing(), return_exceptions=True)
    hops = parse_trace(trace_xml) if isinstance(trace_xml, str) else []
    wan, home = (await _router_wan(hops), await _home()) if want_path else (None, ())
    ip = ip if isinstance(ip, str) else None
    result = {"public_ip": ip, "public_ip_status": await _ip_status(ip) if want_ip else "off", "hops": hops[:5], **classify(hops, wan, home),
              "ts": time.time(), "checks": {"public_ip": want_ip, "path": want_path}}
    _log(result)
    return result


_IP_LOG = {"redirected": "non letto, le richieste DNS sono deviate", "no_reply": "non letto, nessuna risposta", "off": "spento"}


def _log(result: dict) -> None:
    ip = result["public_ip"] or _IP_LOG.get(result.get("public_ip_status"), "-")
    logger.info("Internet: IP pubblico %s, salti %s, doppio NAT %s, CGNAT %s", ip, " > ".join(result["hops"]) or "-",
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
