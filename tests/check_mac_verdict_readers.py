"""Single MAC layer, the verdict read (1.0 step P2): the rules that judged on their own whether a MAC is lent by a repeater (the Bonjour memory, the
clients behind a repeater) now read the one verdict that macclassify gives every cycle (mac_class, written by store_mac_verdict alone). Proved here:
what the snapshot of the verdict says and when it is refreshed, what each rule does with it (a phone that changed address three times in a week is
not a lent MAC any more; a repeater whose clients are asleep still is; a host with two addresses at once is a device of its own), and - with a spy on
the database and on the source - that the verdict is read by one function, through one step, and that the old rules are gone."""
import asyncio
import inspect
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, macverdict  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.scan import mdns_listener as ml  # noqa: E402
from app.storage.history import History  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "vedetta" / "app"
Obs = maclayer.Observation
LENDER, PHONE, HOST, PLAIN = "00:11:22:00:0A:01", "00:11:22:00:0A:02", "00:11:22:00:0A:03", "00:11:22:00:0A:04"
VRRP = "00:00:5E:00:01:07"
DAY = 86400


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# a week of a network: a repeater answering three addresses at once (its clients awake on the first day only), a phone that got a new address
# three times (one after the other), a host with two addresses at once, a plain device, a virtual router MAC
H = History(Path(tempfile.mkdtemp()) / "vedetta.db")
now = time.time()
t0 = now - 6 * DAY
for i in range(10):
    t = t0 + i * 60
    H.observe([Obs(f"10.0.10.{20 + k}", LENDER, "arp", t) for k in range(3)] + [Obs("10.0.10.40", HOST, "arp", t), Obs("10.0.10.41", HOST, "arp", t),
              Obs("10.0.10.50", PLAIN, "arp", t), Obs("10.0.10.1", VRRP, "arp", t)])
for d, ip in enumerate(("10.0.10.60", "10.0.10.61", "10.0.10.62")):
    H.observe([Obs(ip, PHONE, "arp", t0 + (d + 1) * DAY + k * 60) for k in range(5)])
H.observe([Obs("10.0.10.20", LENDER, "arp", now - 60)])           # today: the clients behind the repeater sleep, it answers one address only

# 1) the snapshot: empty before any verdict, filled by the cycle step that stores the verdict, read without case or separator mattering
macverdict.refresh({})
assert macverdict.kind(LENDER) is None and not macverdict.shared(LENDER), "no verdict yet: nothing is called lent"
run(maclayer.store_verdict(H, now=now))
assert {m: macverdict.kind(m) for m in (LENDER, PHONE, HOST, PLAIN, VRRP)} == {
    LENDER: "lender", PHONE: "normal", HOST: "multi_address", PLAIN: "normal", VRRP: "virtual"}, "the snapshot is the stored verdict"
assert macverdict.kind(LENDER.lower()) == "lender" and macverdict.kind(LENDER.replace(":", "-").lower()) == "lender"
assert macverdict.shared(LENDER) and macverdict.shared(VRRP), "a lender and a virtual MAC name no single device"
assert not any(macverdict.shared(m) for m in (PHONE, HOST, PLAIN)), "a phone that moved, a host with two addresses, a plain device: each is its own"
assert macverdict.lenders() == frozenset({LENDER}), macverdict.lenders()

# at start the verdict of the last run is read back before the first cycle (the Bonjour listener starts at once)
macverdict.refresh({})
maclayer.load_verdict(H)
assert macverdict.kind(LENDER) == "lender"


# a failure reading the verdict is logged and the last snapshot stands; it never reaches the caller
class NoRead(History):
    def mac_kinds(self):
        raise RuntimeError("disk")


maclayer.load_verdict(NoRead(Path(tempfile.mkdtemp()) / "vedetta.db"))
assert macverdict.kind(LENDER) == "lender", "a failed read keeps the last verdict"

# 2) the Bonjour memory (was mdns_listener: "more than one address now, or three addresses in seven days")
ml.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
ml.by_mac.clear()
ml.by_ip.clear()
ARP = {"10.0.10.20": LENDER, "10.0.10.21": LENDER, "10.0.10.62": PHONE, "10.0.10.40": HOST, "10.0.10.41": HOST}
ml._mac_for_ip = lambda ip: (ARP.get(ip) or "").lower() or None
ml.record("10.0.10.21", "_companion-link._tcp", "phone-behind-repeater", '""')
assert LENDER.lower() not in ml.by_mac and "10.0.10.21" in ml.by_ip, "a client behind the repeater keeps its card by address"
assert ml.lookup(LENDER, "10.0.10.20") is None, "the repeater gets nothing of its client"
ARP.pop("10.0.10.21")                                            # the client sleeps: the repeater is at one address now, the verdict still says lent
ml.record("10.0.10.20", "_companion-link._tcp", "while-asleep", '""')
assert LENDER.lower() not in ml.by_mac, "who is awake right now does not decide"
ml.record("10.0.10.62", "_companion-link._tcp", "Phone-1", '""')
assert ml.lookup(PHONE)["name"] == "Phone-1", "a phone that got a new address three times in a week keeps its name under its MAC (it was called lent before)"
ml.record("10.0.10.41", "_http._tcp", "nas", '""')
assert ml.lookup(HOST)["name"] == "nas", "a host with two addresses at once is one device: its name stays under its MAC"
assert not hasattr(ml, "_at_several_addresses") and not hasattr(ml, "lent_in_memory") and not hasattr(ml, "LENT_MIN_ADDRESSES"), "the old rule is gone"

# 3) the clients behind a repeater (was roles: "the same MAC at two addresses or more")
UPNP = {"10.0.10.20": {"types": ["WFADevice"], "name": "Repeater"}}
VIEW = {"10.0.10.20": {"mac": LENDER}, "10.0.10.21": {"mac": LENDER.lower()}, "10.0.10.22": {"mac": LENDER},
        "10.0.10.40": {"mac": HOST}, "10.0.10.41": {"mac": HOST}, "10.0.10.1": {"mac": VRRP}, "10.0.10.2": {"mac": VRRP}}
r = roles.compute(gateway=None, dhcp_servers=[], dns_servers=[], upnp=UPNP, arp=VIEW, lenders=macverdict.lenders())
assert set(r["via"]) == {"10.0.10.21", "10.0.10.22"} and r["via"]["10.0.10.21"]["ip"] == "10.0.10.20", r["via"]
assert r["by_ip"]["10.0.10.20"] == {"ap": "upnp", "repeater": "upnp"}, r["by_ip"]
r = roles.compute(gateway=None, dhcp_servers=[], dns_servers=[], upnp={}, arp=VIEW, lenders=frozenset())
assert r["via"] == {}, "without the verdict of a lender nobody is put behind a repeater: two addresses alone are a host, a virtual MAC is shared by design"

# 4) SPY on the database: every read of mac_class, and the function that issued it, over cycles, a start and the rules at work
H4 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
READS: list = []
READ = re.compile(r"^\s*SELECT\b[^;]*\bFROM\s+mac_class\b", re.IGNORECASE)


def spy(sql):
    if READ.search(sql):
        names = [f.function for f in inspect.stack()[1:]]
        READS.append(next((n for n in names if n in ("mac_kinds", "_store_mac_class")), names[0]))


H4._db.set_trace_callback(spy)
for i in range(5):
    H4.observe([Obs(f"10.0.11.{k}", LENDER, "arp", now - 300 + i * 60) for k in range(1, 4)])
    run(maclayer.record({"10.0.11.1": {"mac": LENDER}}, H4))
    ml.lookup(LENDER, "10.0.11.2")
maclayer.load_verdict(H4)
assert READS and "mac_kinds" in READS, "the spy sees the reads (a spy that sees nothing proves nothing)"
assert set(READS) <= {"mac_kinds", "_store_mac_class"}, READS
assert macverdict.kind(LENDER) == "lender"

# SPY on the source: one function reads the verdict, one module hands it to the snapshot, the rules ask the snapshot, the old counts are gone
reads, readers, refreshers, old = [], [], [], []
for f in APP.rglob("*.py"):
    text = f.read_text(encoding="utf-8")
    rel = f.relative_to(APP).as_posix()
    reads += [rel for _ in re.finditer(r"SELECT[^\"']*\bFROM\s+mac_class\b", text, re.IGNORECASE)]
    readers += [rel for _ in re.finditer(r"\.mac_kinds\(", text)]
    refreshers += [rel for _ in re.finditer(r"macverdict\.refresh\(", text)]
    old += [rel for _ in re.finditer(r"mac_ip_counts|_at_several_addresses|lent_in_memory|LENT_MIN_ADDRESSES", text)]
assert reads == ["storage/history_maclayer.py"] * 2, "the writer's own comparison and the one reader: " + repr(reads)
assert readers == ["maclayer.py"], "one function reads the verdict, from one module: " + repr(readers)
assert refreshers == ["maclayer.py"], "one module fills the snapshot: " + repr(refreshers)
assert old == [], "a rule still counts the addresses of a MAC by itself: " + repr(old)
assert "macverdict.shared(" in (APP / "scan" / "mdns_listener.py").read_text(encoding="utf-8")
assert "lenders=macverdict.lenders()" in (APP / "recognition" / "roles.py").read_text(encoding="utf-8")
print("TUTTO OK")
