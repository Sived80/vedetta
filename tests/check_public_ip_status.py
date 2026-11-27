# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The public IP when it cannot be read (scan/internet.py, recognition/roles.py). On a network whose router or DNS filter answers the queries to port 53
in place of OpenDNS, myip.opendns.com gives no address: one more query to the same address, debug.opendns.com TXT, tells the two cases apart. The
real OpenDNS answers it with a "server <name>" line: an answer without that line means the DNS is redirected (it does not fix itself: next check in
6 hours), no answer at all is transient (one quick retry, of the public IP only, after 15 minutes). The text of that TXT carries the public address
of the client: only the yes/no is kept, never the text. Everything here is faked: no packet leaves."""
import asyncio
import json
import logging
import os
import random
import struct
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
from app.recognition import roles  # noqa: E402
from app.scan import internet, scanner  # noqa: E402
from app.storage import journal  # noqa: E402

journal.PATH = Path(tempfile.mkdtemp()) / "journal.jsonl"
internet.DNS_TIMEOUT_S = 0.05                     # a missing answer is waited for 50 ms, not 3 s
SECRET_SOURCE = "203.0.113.77"                    # what the debug TXT says about the client: must never be kept
REAL_TXT = ["server m99.example", "flags 20 0 2f4 0", "originid 0", "actype 0", "source " + SECRET_SOURCE + ":40000"]


def header(qid, an, flags=0x8180):
    return struct.pack(">HHHHHH", qid, flags, 1, an, 0, 0)


def question(name, qtype):
    return b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00" + struct.pack(">HH", qtype, 1)


def txt_answer(qid, texts):
    """One TXT record per text (as OpenDNS does), each one a single character string."""
    body = b""
    for s in texts:
        rd = bytes([len(s)]) + s.encode()
        body += b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 0, len(rd)) + rd
    return header(qid, len(texts)) + question("debug.opendns.com", 16) + body


def a_answer(qid, ip):
    rec = b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 0, 4) + bytes(int(x) for x in ip.split("."))
    return header(qid, 1) + question("myip.opendns.com", 1) + rec


def empty_answer(qid, name, qtype, rcode=3):
    return header(qid, 0, 0x8180 | rcode) + question(name, qtype)


# --- the TXT parser: pure and bounded
assert internet.parse_txt_answer(txt_answer(0x1234, REAL_TXT), 0x1234) == REAL_TXT
assert internet.parse_txt_answer(txt_answer(0x1234, REAL_TXT), 0x4321) is None, "an answer to another query is not read"
assert internet.parse_txt_answer(txt_answer(0x1234, ["hello"]), 0x1234) == ["hello"], "a TXT without the server line: read as it is"
assert internet.parse_txt_answer(empty_answer(0x1234, "debug.opendns.com", 16), 0x1234) == [], "a reply with no record: no text"
two = bytes([3]) + b"abc" + bytes([2]) + b"de"                # one record made of two character strings
multi = header(7, 1) + question("debug.opendns.com", 16) + b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 0, len(two)) + two
assert internet.parse_txt_answer(multi, 7) == ["abc", "de"]
good = txt_answer(0x55, REAL_TXT)
for cut in range(len(good)):                          # every truncation: never an error, never a text that was not whole
    got = internet.parse_txt_answer(good[:cut], 0x55)
    assert got is None or all(s in REAL_TXT for s in got), (cut, got)
bad_len = header(9, 1) + question("debug.opendns.com", 16) + b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 0, 200) + b"\x05ab"
assert internet.parse_txt_answer(bad_len, 9) == [], "a record longer than the packet is dropped"
inner = header(9, 1) + question("debug.opendns.com", 16) + b"\xc0\x0c" + struct.pack(">HHIH", 16, 1, 0, 3) + b"\x09ab"
assert internet.parse_txt_answer(inner, 9) == [], "a string longer than its record is dropped"
assert internet.parse_txt_answer(b"\x00\x09\x80", 9) is None and internet.parse_txt_answer(b"", 9) is None
rnd = random.Random(7)
for _ in range(3000):
    blob = bytes(rnd.randrange(256) for _ in range(rnd.randrange(60)))
    internet.parse_txt_answer(b"\x00\x09\x81\x80" + blob, 9)          # garbage after a valid start: no exception
    internet.parse_a_answer(b"\x00\x09\x81\x80" + blob, 9)
assert internet.parse_a_answer(a_answer(0x2222, "203.0.113.9"), 0x2222) == "203.0.113.9", "the A parser still reads its answer"

# --- check() against a faked OpenDNS: what it answers to each query is the script of the case
sent = []
SCRIPT = {}


def read_query(data):
    qid, pos, labels = struct.unpack(">H", data[:2])[0], 12, []
    while data[pos]:
        labels.append(data[pos + 1:pos + 1 + data[pos]].decode())
        pos += 1 + data[pos]
    return qid, ".".join(labels), struct.unpack(">H", data[pos + 1:pos + 3])[0]


class FakeTransport:
    def __init__(self, proto):
        self.proto = proto

    def sendto(self, data):
        qid, name, qtype = read_query(data)
        sent.append((name, qtype))
        reply = SCRIPT.get((name, qtype))
        if reply is not None:
            asyncio.get_running_loop().call_soon(self.proto.datagram_received, reply(qid), (internet.OPENDNS, 53))

    def close(self):
        pass


async def fake_endpoint(factory, remote_addr=None, **_kw):
    assert remote_addr == (internet.OPENDNS, 53), remote_addr
    proto = factory()
    return FakeTransport(proto), proto


nmap_calls = []


async def fake_nmap(args, semaphore=None):
    nmap_calls.append(args)
    return '<nmaprun><host><trace><hop ttl="1" ipaddr="192.0.2.1"/><hop ttl="2" ipaddr="198.51.100.1"/></trace></host></nmaprun>'


async def no_home():
    return ()


scanner._run_nmap = fake_nmap
internet._home = no_home                       # the networks of the house are not read (no real network)
records = []
handler = logging.Handler()
handler.emit = lambda rec: records.append(rec.getMessage())
logging.getLogger("dashboard").addHandler(handler)


def run_check(script, **kw):
    sent.clear()
    nmap_calls.clear()
    SCRIPT.clear()
    SCRIPT.update(script)
    loop = asyncio.new_event_loop()
    loop.create_datagram_endpoint = fake_endpoint
    try:
        return loop.run_until_complete(internet.check(**kw))
    finally:
        loop.close()


MYIP, DEBUG = ("myip.opendns.com", 1), ("debug.opendns.com", 16)
os.environ.pop("VEDETTA_INTERNET_PUBLIC_IP", None)
os.environ["VEDETTA_INTERNET_PATH"] = "true"

r = run_check({MYIP: lambda q: a_answer(q, "203.0.113.9")})
assert r["public_ip"] == "203.0.113.9" and r["public_ip_status"] == "ok", r
assert sent == [MYIP], ("an address: no second query", sent)

r = run_check({MYIP: lambda q: empty_answer(q, *MYIP), DEBUG: lambda q: txt_answer(q, ["no such server here"])})
assert r["public_ip"] is None and r["public_ip_status"] == "redirected", r
assert sent == [MYIP, DEBUG], ("no address: exactly one more query, the debug TXT", sent)

r = run_check({MYIP: lambda q: empty_answer(q, *MYIP), DEBUG: lambda q: empty_answer(q, *DEBUG)})
assert r["public_ip_status"] == "redirected", "a reply with no TXT at all: redirected too"

r = run_check({})
assert r["public_ip"] is None and r["public_ip_status"] == "no_reply" and sent == [MYIP, DEBUG], (r, sent)

records.clear()
r = run_check({DEBUG: lambda q: txt_answer(q, REAL_TXT)})
assert r["public_ip_status"] == "no_reply", "the real OpenDNS answers but gave no address: transient"
assert SECRET_SOURCE not in json.dumps(r) and "m99" not in json.dumps(r), "the text of the debug TXT is never kept"
assert records and not any(SECRET_SOURCE in m or "m99" in m for m in records), ("nor written in the log", records)
assert any("IP pubblico" in m for m in records), records

os.environ["VEDETTA_INTERNET_PUBLIC_IP"] = "false"
r = run_check({})
assert sent == [] and r["public_ip"] is None and r["public_ip_status"] == "off" and r["checks"]["public_ip"] is False, (r, sent)
os.environ.pop("VEDETTA_INTERNET_PUBLIC_IP")

# --- the quick retry asks the public IP again, and only that: the path (traceroute, UPnP) is kept from the last check
before = run_check({})
assert len(nmap_calls) == 1 and before["hops"] == ["192.0.2.1", "198.51.100.1"]
r = run_check({MYIP: lambda q: a_answer(q, "203.0.113.9")}, previous=before)
assert nmap_calls == [] and sent == [MYIP], ("the quick retry: one DNS query, no traceroute", nmap_calls, sent)
assert r["public_ip"] == "203.0.113.9" and r["public_ip_status"] == "ok" and r["hops"] == before["hops"] and r["ts"] >= before["ts"], r

# --- roles: when the next check is due
calls = []


def fake_check_with(status):
    async def fake_check(previous=None):
        calls.append(previous)
        return {"public_ip": None if status != "ok" else "203.0.113.9", "public_ip_status": status, "hops": [], "cgnat": False,
                "double_nat": False, "maybe_double_nat": False, "checks": {"public_ip": True, "path": True}, "ts": time.time()}
    return fake_check


def step(status, age_s):
    """One refresh of roles with the last check `age_s` seconds old: whether the check ran, and how (full / ip)."""
    roles._rt.internet_check = fake_check_with(status)
    roles._rt.internet["ts"] = time.time() - age_s
    calls.clear()
    asyncio.new_event_loop().run_until_complete(roles._run_jobs_and_check_internet([]))
    return None if not calls else "full" if calls[0] is None else "ip"


roles._rt.internet.update(data=None, ts=0.0)
assert step("no_reply", 10 ** 9) == "full", "the first check is a full one"
lines = len(journal.PATH.read_text(encoding="utf-8").splitlines())
assert step("no_reply", 14 * 60) is None, "after no reply: nothing before 15 minutes"
assert step("no_reply", 15 * 60 + 1) == "ip", "after no reply: the public IP again after 15 minutes"
assert len(journal.PATH.read_text(encoding="utf-8").splitlines()) == lines, "the quick retry writes no journal line (the path did not change)"
assert step("no_reply", 3 * 3600) is None, "a second no reply: back to the 6 hours"
assert step("redirected", roles.DISCOVER_EVERY_S + 1) == "full"
assert step("redirected", 16 * 60) is None and step("redirected", 3 * 3600) is None, "redirected does not fix itself: no quick retry"
assert step("no_reply", roles.DISCOVER_EVERY_S + 1) == "full"
assert step("ok", 15 * 60 + 1) == "ip", "each 6-hour check without reply gets its one quick retry"
assert step("ok", 15 * 60 + 1) is None and step("ok", roles.DISCOVER_EVERY_S + 1) == "full", "after an address: the 6 hours"
print("ALL OK")
