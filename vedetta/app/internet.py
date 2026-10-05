"""Uscita verso internet: IP pubblico, doppio NAT, CGNAT del provider.

  IP pubblico  query DNS standard al resolver di OpenDNS per myip.opendns.com: la
               risposta e' l'indirizzo da cui la query arriva (nessuna API web)
  percorso     traceroute di nmap (--traceroute) verso 1.1.1.1: i primi salti
  doppio NAT   due o piu' salti con IP privati (RFC 1918) prima del primo pubblico:
               c'e' un altro router (es. il modem del provider) davanti al tuo
  CGNAT        un salto in 100.64.0.0/10 (RFC 6598) prima del primo pubblico: il
               provider condivide l'IP pubblico tra piu' clienti"""
import asyncio
import ipaddress
import random
import struct
import time
import xml.etree.ElementTree as ET

from .applog import logger

OPENDNS = "208.67.222.222"
TRACE_TARGET = "1.1.1.1"
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


def build_query(qid: int, name: str, qtype: int = 1) -> bytes:
    qname = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + bytes([0])
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", qtype, 1)


def _skip_name(data: bytes, pos: int) -> int:
    while pos < len(data):
        length = data[pos]
        if length == 0:
            return pos + 1
        if length & 0xC0 == 0xC0:
            return pos + 2
        pos += 1 + length
    return pos


def parse_a_answer(data: bytes, qid: int) -> str | None:
    """Primo record A della risposta, None se assente o non valida."""
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


class _Reply(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.data = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr) -> None:
        if not self.data.done():
            self.data.set_result(data)


async def public_ip(timeout: float = 3.0) -> str | None:
    loop = asyncio.get_running_loop()
    qid = random.randint(1, 65535)
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
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    hops = []
    for hop in root.findall("host/trace/hop"):
        try:
            hops.append((int(hop.get("ttl", "0")), hop.get("ipaddr")))
        except ValueError:
            continue
    return [ip for _, ip in sorted(hops) if ip]


def classify(hops: list[str]) -> dict:
    """Salti fino al primo pubblico: quanti privati, se c'e' CGNAT."""
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
    return {"private_hops": private, "double_nat": len(private) >= 2, "cgnat": cgnat}


async def check() -> dict:
    from .scanner import _LIGHT_NMAP_SEMAPHORE, _run_nmap
    trace_xml, ip = await asyncio.gather(
        _run_nmap(["-sn", "-Pn", "--traceroute", "--max-retries", "1", "--host-timeout", "20s", TRACE_TARGET],
                  semaphore=_LIGHT_NMAP_SEMAPHORE),
        public_ip(), return_exceptions=True)
    hops = parse_trace(trace_xml) if isinstance(trace_xml, str) else []
    result = {"public_ip": ip if isinstance(ip, str) else None, "hops": hops[:5], **classify(hops), "ts": time.time()}
    logger.info("Internet: IP pubblico %s, salti %s, doppio NAT %s, CGNAT %s", result["public_ip"] or "-",
                " > ".join(result["hops"]) or "-", "si" if result["double_nat"] else "no", "si" if result["cgnat"] else "no")
    return result
