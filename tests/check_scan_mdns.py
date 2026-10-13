"""Reference test of the pure parts of scan/scan_mdns.py: the TXT string (model / manufacturer keys and the 60 characters limit), the PTR query
packet built by hand, DNS names with compression pointers, the answer parser (first PTR, garbage and loops are survived), the direct
"who has this IP" query with a fake network, and the completion of the names with the active query only where the passive scan found none."""
import asyncio
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_mdns as sm  # noqa: E402

# TXT strings
assert sm._props_to_txt({b"md": b"Chromecast", "fn": "Salotto", b"empty": None, b"q": b'a"b'}) == '"md=Chromecast" "fn=Salotto" "q=ab"'
assert sm._props_to_txt(None) == "" and sm._props_to_txt({}) == ""
txt = '"model=iPhone15,2" "mf=Apple" "x=1"'
assert sm.parse_mdns_txt(txt) == {"model": "iPhone15,2", "manufacturer": "Apple"}
assert sm.parse_mdns_txt('"am=AppleTV6,2" "manufacturer=Cupertino"') == {"model": "AppleTV6,2", "manufacturer": "Cupertino"}
assert sm.parse_mdns_txt('"md=' + "x" * 100 + '"')["model"] == "x" * 60 and sm.parse_mdns_txt("nothing") == {}

# the query packet
q = sm._build_ptr_query("192.168.1.7")
assert q[:12] == struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
assert b"\x017\x011\x03168\x03192\x07in-addr\x04arpa\x00" in q and q.endswith(b"\x00" + struct.pack(">HH", 12, 0x8001))
assert sm._read_dns_name(q, 12)[0] == "7.1.168.192.in-addr.arpa"


def packet(answers):
    return struct.pack(">HHHHHH", 0, 0x8400, 1, len(answers), 0, 0) + q[12:] + b"".join(answers)


def name_bytes(name):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"


def rr(rtype, rdata, name=b"\xc0\x0c"):
    return name + struct.pack(">HHIH", rtype, 1, 120, len(rdata)) + rdata


ptr = rr(12, name_bytes("iPhone-di-Caio.local"))
assert sm._parse_ptr_answer(packet([ptr])) == "iPhone-di-Caio.local"
assert sm._parse_ptr_answer(packet([rr(1, b"\x0a\x00\x00\x01"), ptr])) == "iPhone-di-Caio.local", "a non-PTR record is skipped"
assert sm._parse_ptr_answer(packet([rr(1, b"\x0a\x00\x00\x01")])) is None
compressed = rr(12, b"\x05mydev\xc0\x20")                  # "mydev" + pointer into the question name
assert sm._parse_ptr_answer(packet([compressed]))
assert sm._parse_ptr_answer(b"short") is None and sm._parse_ptr_answer(b"\x00" * 12 + b"\xff" * 5) is None
loop_data = b"\xc0\x00" * 2
try:
    sm._read_dns_name(loop_data, 0)
    raise AssertionError("a pointer loop must be refused")
except ValueError:
    pass

# the direct query with a fake network
sent = []


class FakeTransport:
    def __init__(self, future, reply):
        self.future, self.reply = future, reply

    def sendto(self, data):
        sent.append(data)
        if self.reply is not None:
            self.future.set_result(self.reply)

    def close(self):
        sent.append("closed")


class FakeLoop:
    reply = None
    fail = False

    def create_future(self):
        return asyncio.get_event_loop().create_future()

    async def create_datagram_endpoint(self, factory, remote_addr):
        if self.fail:
            raise OSError("no route")
        proto = factory()
        return FakeTransport(proto.future, self.reply), proto


fake = FakeLoop()
sm.asyncio.get_running_loop = lambda: fake
run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731

fake.reply = packet([rr(12, name_bytes("Salotto-TV.local."))])
assert run(sm.resolve_mdns_name("192.168.1.7")) == "Salotto-TV", "the .local suffix and the trailing dot go"
assert sent[0] == q and sent[-1] == "closed"
assert run(sm.resolve_mdns_name("not-an-ip")) is None
fake.reply = b"garbage"
assert run(sm.resolve_mdns_name("192.168.1.7")) is None
fake.fail = True
assert run(sm.resolve_mdns_name("192.168.1.7")) is None
fake.fail = False

# names: the passive ones stay, the active query only for the others
asked = []


async def fake_resolve(ip):
    asked.append(ip)
    return {"10.0.0.2": "two", "10.0.0.3": None}.get(ip)


sm.resolve_mdns_name = fake_resolve
got = run(sm.resolve_names(["10.0.0.1", "10.0.0.2", "10.0.0.3"], {"10.0.0.1": "one"}))
assert got == {"10.0.0.1": "one", "10.0.0.2": "two"} and asked == ["10.0.0.2", "10.0.0.3"]
passive = {"10.0.0.1": "one"}
run(sm.resolve_names(["10.0.0.1"], passive))
assert passive == {"10.0.0.1": "one"} and asked == ["10.0.0.2", "10.0.0.3"], "nothing missing: no active query, and the caller's dict is not touched"
print("TUTTO OK")
