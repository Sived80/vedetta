"""The SNMP v2c reader of the router's ARP table (scan/snmp.py): BER both ways, a GETBULK walk that stops at the end of the subtree, at
an end marker or at a ceiling, an answer that belongs to another request refused, an error-status refused, the old table first and
the newer one when the old is empty, MACs of 6 bytes only (all zeros and broadcast dropped). A fake router answers; one test goes
over real UDP on localhost. Never a SET: only GETNEXT and GETBULK are ever built.
    python tests/check_snmp_arp.py"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import snmp  # noqa: E402

# 1) BER round trips
for parts in ((1, 3, 6, 1, 2, 1, 4, 22, 1, 2), (1, 3, 6, 1, 4, 1, 4413, 1, 300000), (2, 999, 3)):
    tag, value, _ = snmp._read(snmp.oid(parts), 0)
    assert tag == 0x06 and snmp.decode_oid(value) == parts, parts
for n in (0, 1, 127, 128, 255, 256, 65535, 2_000_000_000):
    tag, value, _ = snmp._read(snmp.integer(n), 0)
    assert int.from_bytes(value, "big", signed=True) == n, n
long = snmp.octets(b"x" * 300)
assert snmp._read(long, 0)[1] == b"x" * 300
for bad in (b"", b"\x30", b"\x30\x85\x01\x02\x03\x04\x05", b"\x30\x05\x02"):
    try:
        snmp._read(bad, 0)
        raise AssertionError(bad)
    except snmp.SnmpError:
        pass


# 2) a fake router: a table of OIDs, answers GETBULK with the next ones
def router(table: dict, community="s3cret", lie_id=False, error=0):
    ordered = sorted(table)
    seen = []

    def parse(packet):
        _, msg, _ = snmp._read(packet, 0)
        version, comm, pdu = snmp._children(msg)
        fields = snmp._children(pdu[1])
        rid = int.from_bytes(fields[0][1], "big", signed=True)
        reps = int.from_bytes(fields[2][1], "big")
        start = snmp.decode_oid(snmp._children(snmp._children(fields[3][1])[0][1])[0][1])
        return pdu[0], comm[1].decode(), rid, reps, start

    async def ask(packet):
        kind, comm, rid, reps, start = parse(packet)
        seen.append((kind, comm, start))
        assert kind in (snmp.GET_NEXT, snmp.GET_BULK)                       # never a SET or anything else
        nxt = [o for o in ordered if o > start][:max(1, reps)]
        binds = b"".join(snmp.tlv(0x30, snmp.oid(o) + snmp.octets(table[o])) for o in nxt)
        if len(nxt) < max(1, reps):
            binds += snmp.tlv(0x30, snmp.oid(start + (9,)) + snmp.tlv(0x82, b""))      # endOfMibView
        pdu = snmp.tlv(snmp.RESPONSE, snmp.integer(rid + (1 if lie_id else 0)) + snmp.integer(error) + snmp.integer(0) + snmp.tlv(0x30, binds))
        return snmp.tlv(0x30, snmp.integer(1) + snmp.octets(comm.encode()) + pdu)
    ask.seen = seen
    return ask


V1 = snmp.ARP_V1
table = {V1 + (3, 192, 168, 20, i): bytes([0xAA, 0xBB, 0xCC, 0, 0, i]) for i in range(1, 60)}
table[V1 + (3, 192, 168, 20, 99)] = b"\x00" * 6                            # incomplete entry
table[V1 + (3, 192, 168, 20, 98)] = b"\x01\x02"                            # not 6 bytes
table[(1, 3, 6, 1, 2, 1, 4, 23, 1)] = b"after the table"                   # outside the subtree
ask = router(table)
got = asyncio.run(snmp.arp_table("10.0.0.1", "s3cret", ask=ask))
assert len(got) == 59 and got["192.168.20.1"] == "AA:BB:CC:00:00:01" and "192.168.20.99" not in got and "192.168.20.98" not in got, len(got)
assert all(c == "s3cret" for _, c, _ in ask.seen) and all(k == snmp.GET_BULK for k, _, _ in ask.seen)
assert len(ask.seen) == 4                                                   # 61 rows of the subtree, 20 at a time

# 3) ceilings: rows
rows = asyncio.run(snmp.walk("x", "s3cret", V1, ask=router(table), max_rows=25))
assert len(rows) == 25

# 4) the newer table when the old one is empty
V2 = snmp.ARP_V2
new = {V2 + (5, 1, 4, 10, 1, 20, 7): bytes([0x11, 0x22, 0x33, 0x44, 0x55, 0x66]), V2 + (5, 2, 16) + (0,) * 16: b"\x11" * 6}
assert asyncio.run(snmp.arp_table("x", "s3cret", ask=router(new))) == {"10.1.20.7": "11:22:33:44:55:66"}
assert asyncio.run(snmp.arp_table("x", "s3cret", ask=router({}))) == {}

# 5) an answer to another request, an error-status: refused
for kw in ({"lie_id": True}, {"error": 2}):
    try:
        asyncio.run(snmp.walk("x", "s3cret", V1, ask=router(table, **kw)))
        raise AssertionError(kw)
    except snmp.SnmpError:
        pass


# 5b) a varbind without its value: an SNMP error, not a crash of another kind
broken = snmp.tlv(0x30, snmp.integer(1) + snmp.octets(b"s3cret") + snmp.tlv(snmp.RESPONSE, snmp.integer(7) + snmp.integer(0) + snmp.integer(0)
                  + snmp.tlv(0x30, snmp.tlv(0x30, snmp.oid(V1 + (3, 1, 2, 3, 4))))))
try:
    snmp.response(broken, 7)
    raise AssertionError("a varbind without value accepted")
except snmp.SnmpError:
    pass

# 5c) a router that refuses the old table with an error still gives the newer one
both = router(new)
refuse_old = router({}, error=2)


async def picky(packet):
    start = snmp.decode_oid(snmp._children(snmp._children(snmp._children(snmp._children(snmp._read(packet, 0)[1])[2][1])[3][1])[0][1])[0][1])
    return await (refuse_old if start[:len(V1)] == V1 else both)(packet)
assert asyncio.run(snmp.arp_table("x", "s3cret", ask=picky)) == {"10.1.20.7": "11:22:33:44:55:66"}

# 6) over real UDP on localhost (the fake router behind a socket); a silent host times out
class Agent(asyncio.DatagramProtocol):
    def __init__(self, ask):
        self.ask = ask

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        asyncio.ensure_future(self._answer(data, addr))

    async def _answer(self, data, addr):
        self.transport.sendto(await self.ask(data), addr)


async def over_udp():
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: Agent(router(table)), local_addr=("127.0.0.1", 0))
    port = transport.get_extra_info("sockname")[1]
    try:
        got = await snmp.arp_table("127.0.0.1", "s3cret", port=port)
    finally:
        transport.close()
    assert len(got) == 59
    snmp.TIMEOUT_S = 0.2
    silent, _ = await loop.create_datagram_endpoint(asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0))
    try:
        await snmp.walk("127.0.0.1", "s3cret", V1, port=silent.get_extra_info("sockname")[1])
        raise AssertionError("a silent host answered")
    except asyncio.TimeoutError:
        pass
    finally:
        silent.close()

asyncio.run(over_udp())
print("check_snmp_arp: ok")
