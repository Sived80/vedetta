"""A small SNMP v2c reader, read-only, for ONE thing: the ARP table of the router the person names, with the community the person
writes. Vedetta never tries a community on its own (no "public"), never writes (no SET), never asks a device other than that router.

Only what that needs, no library: BER encoding of GETNEXT / GETBULK requests, decoding of the answer (integers, octet strings,
object identifiers, the three "end" markers), and a walk with its ceilings (rows, time) and the checks on the answer (the same
request-id, no error-status). Pure functions for the bytes; `walk` does the network (UDP, one request at a time).

The table (ipNetToMediaPhysAddress, RFC 1213, 1.3.6.1.2.1.4.22.1.2): index = ifIndex . a . b . c . d, value = the 6 bytes of the MAC;
when a router has only the newer one (ipNetToPhysicalPhysAddress, RFC 4293, 1.3.6.1.2.1.4.35.1.4: index = ifIndex . 1 (ipv4) . 4 .
a . b . c . d), that one is read."""
import asyncio
import os

ARP_V1 = (1, 3, 6, 1, 2, 1, 4, 22, 1, 2)
ARP_V2 = (1, 3, 6, 1, 2, 1, 4, 35, 1, 4)
GET_NEXT, GET_BULK, RESPONSE = 0xA1, 0xA5, 0xA2
END_TAGS = (0x80, 0x81, 0x82)            # noSuchObject, noSuchInstance, endOfMibView
MAX_ROWS = 4096
MAX_SECONDS = 20.0
TIMEOUT_S = 3.0
RETRIES = 1
BULK = 20
MAX_PACKET = 65507


class SnmpError(ValueError):
    pass


# ---- BER ----
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _len(len(value)) + value


def integer(n: int) -> bytes:
    return tlv(0x02, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def octets(b: bytes) -> bytes:
    return tlv(0x04, b)


def _base128(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def oid(parts: tuple) -> bytes:
    if len(parts) < 2:
        raise SnmpError("an OID has at least two parts")
    return tlv(0x06, _base128(40 * parts[0] + parts[1]) + b"".join(_base128(p) for p in parts[2:]))


def request(community: str, request_id: int, start: tuple, bulk: int = 0) -> bytes:
    """A GETNEXT (bulk=0) or a GETBULK of `bulk` repetitions for one OID."""
    varbinds = tlv(0x30, tlv(0x30, oid(start) + tlv(0x05, b"")))
    if bulk:
        pdu = tlv(GET_BULK, integer(request_id) + integer(0) + integer(bulk) + varbinds)
    else:
        pdu = tlv(GET_NEXT, integer(request_id) + integer(0) + integer(0) + varbinds)
    return tlv(0x30, integer(1) + octets(community.encode()) + pdu)


def _read(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """(tag, value, next position); SnmpError on a truncated or malformed element."""
    if pos + 2 > len(data):
        raise SnmpError("truncated")
    tag, first = data[pos], data[pos + 1]
    pos += 2
    if first & 0x80:
        n = first & 0x7F
        if n == 0 or n > 4 or pos + n > len(data):
            raise SnmpError("bad length")
        length, pos = int.from_bytes(data[pos:pos + n], "big"), pos + n
    else:
        length = first
    if pos + length > len(data):
        raise SnmpError("truncated")
    return tag, data[pos:pos + length], pos + length


def _children(value: bytes) -> list[tuple[int, bytes]]:
    out, pos = [], 0
    while pos < len(value):
        tag, v, pos = _read(value, pos)
        out.append((tag, v))
    return out


def decode_oid(value: bytes) -> tuple:
    if not value:
        raise SnmpError("empty OID")
    numbers, n = [], 0
    for b in value:
        n = (n << 7) | (b & 0x7F)
        if not b & 0x80:
            numbers.append(n)
            n = 0
    first = numbers[0] if numbers else 0
    head = (first // 40, first % 40) if first < 80 else (2, first - 80)
    return head + tuple(numbers[1:])


def response(data: bytes, request_id: int) -> list[tuple[tuple, int, bytes]]:
    """The varbinds of an answer: [(oid, tag of the value, raw value)]; SnmpError if it is not the answer to this request."""
    tag, msg, _ = _read(data, 0)
    parts = _children(msg) if tag == 0x30 else []
    if len(parts) != 3 or parts[2][0] != RESPONSE:
        raise SnmpError("not an SNMP response")
    fields = _children(parts[2][1])
    if len(fields) != 4 or int.from_bytes(fields[0][1], "big", signed=True) != request_id:
        raise SnmpError("another request's answer")
    if int.from_bytes(fields[1][1], "big", signed=True):
        raise SnmpError(f"error-status {int.from_bytes(fields[1][1], 'big', signed=True)}")
    binds = []
    for _, vb in _children(fields[3][1]):
        pair = _children(vb)
        if len(pair) != 2 or pair[0][0] != 0x06:
            raise SnmpError("malformed varbind")
        binds.append((decode_oid(pair[0][1]), pair[1][0], pair[1][1]))
    return binds


# ---- the walk ----
class _Once(asyncio.DatagramProtocol):
    def __init__(self):
        self.answer: asyncio.Future = asyncio.get_running_loop().create_future()

    def datagram_received(self, data, addr):
        if not self.answer.done():
            self.answer.set_result(data)

    def error_received(self, exc):
        if not self.answer.done():
            self.answer.set_exception(exc)


async def _ask(host: str, port: int, packet: bytes, timeout: float) -> bytes:
    loop = asyncio.get_running_loop()
    transport, proto = await loop.create_datagram_endpoint(_Once, remote_addr=(host, port))
    try:
        transport.sendto(packet)
        return await asyncio.wait_for(proto.answer, timeout)
    finally:
        transport.close()


async def walk(host: str, community: str, base: tuple, *, port: int = 161, max_rows: int = MAX_ROWS, max_seconds: float = MAX_SECONDS,
               ask=None) -> list[tuple[tuple, int, bytes]]:
    """Every row under `base`, in order: GETBULK (BULK at a time), until the answers leave the subtree, an end marker, or a ceiling.
    `ask(packet) -> bytes` lets a test answer instead of the network."""
    ask = ask or (lambda packet: _ask(host, port, packet, TIMEOUT_S))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_seconds
    rid = int.from_bytes(os.urandom(3), "big")
    rows, current = [], base
    while len(rows) < max_rows and loop.time() < deadline:
        rid += 1
        binds = response(await _with_retry(ask, request(community, rid, current, BULK)), rid)
        fresh = [(o, t, v) for o, t, v in binds if o[:len(base)] == base and t not in END_TAGS and o > current]
        rows += fresh[:max_rows - len(rows)]
        if len(fresh) < len(binds) or not fresh:
            break
        current = fresh[-1][0]
    return rows


async def _with_retry(ask, packet: bytes) -> bytes:
    for _ in range(RETRIES):
        try:
            return await ask(packet)
        except (asyncio.TimeoutError, OSError):
            continue
    return await ask(packet)          # the last try: its error goes to the caller


# ---- the ARP table ----
def mac_text(value: bytes) -> str | None:
    if len(value) != 6 or value in (b"\x00" * 6, b"\xff" * 6):
        return None
    return ":".join(f"{b:02X}" for b in value)


def arp_rows(rows: list[tuple[tuple, int, bytes]], base: tuple) -> dict[str, str]:
    """{IPv4: MAC} from the rows of one of the two tables (the first MAC for an address wins)."""
    out: dict[str, str] = {}
    for o, tag, value in rows:
        suffix = o[len(base):]
        if base == ARP_V1 and len(suffix) == 5:
            ip = suffix[1:]
        elif base == ARP_V2 and len(suffix) == 7 and suffix[1] == 1 and suffix[2] == 4:
            ip = suffix[3:]
        else:
            continue
        mac = mac_text(value) if tag == 0x04 else None
        if mac and all(0 <= p <= 255 for p in ip):
            out.setdefault(".".join(map(str, ip)), mac)
    return out


async def arp_table(host: str, community: str, **kw) -> dict[str, str]:
    """The router's {IPv4: MAC}: the old table first, the newer one when the old is empty or refused (the error of the old one is
    raised only when the newer one gives nothing either)."""
    refused = None
    for base in (ARP_V1, ARP_V2):
        try:
            table = arp_rows(await walk(host, community, base, **kw), base)
        except SnmpError as exc:
            refused = refused or exc
            continue
        if table:
            return table
    if refused:
        raise refused
    return {}
