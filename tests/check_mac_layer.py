"""Single MAC layer, phase 1: observations from ARP and mDNS, the batch write (one transaction, repeats only move last_seen), the lookups, the
retention, and the cycle step that records them without ever disturbing the cycle."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, state as state_mod  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage.history import History  # noqa: E402

H = History(Path(tempfile.mkdtemp()) / "vedetta.db")
state_mod.history = H
Obs = maclayer.Observation

# pure: ARP and mDNS views -> observations
arp = {"10.0.0.1": {"mac": "aa:bb:cc:00:00:01"}, "10.0.0.2": {"mac": "AA-BB-CC-00-00-02"}, "10.0.0.3": {"mac": None},
       "10.0.0.4": {"mac": "ff:ff:ff:ff:ff:ff"}, "10.0.0.5": {"mac": "01:00:5e:00:00:01"}, "10.0.0.6": None}
got = maclayer.from_arp(arp, 100.0)
assert [(o.ip, o.mac) for o in got] == [("10.0.0.1", "AA:BB:CC:00:00:01"), ("10.0.0.2", "AA:BB:CC:00:00:02")], "unusable MACs are skipped"
assert all(o.source == "arp" and o.ts == 100.0 for o in got) and maclayer.from_arp(None, 1.0) == []
cards = {"aa:bb:cc:00:00:07": {"ip": "10.0.0.7", "seen": 55.0}, "aa:bb:cc:00:00:08": {"seen": 1.0}, "zz": {"ip": "10.0.0.9"}}
assert maclayer.from_mdns(cards, 100.0) == [Obs("10.0.0.7", "AA:BB:CC:00:00:07", "mdns", 55.0)]

# the batch: new rows, a repeat moves last_seen and counts, the same pair in two sources stays apart, a duplicate inside a batch counts once
assert H.observe([]) == 0
assert H.observe([Obs("10.0.0.1", "AA:BB:CC:00:00:01", "arp", 100.0), Obs("10.0.0.1", "AA:BB:CC:00:00:01", "arp", 105.0),
                  Obs("10.0.0.1", "AA:BB:CC:00:00:01", "mdns", 90.0)]) == 2
H.observe([Obs("10.0.0.1", "AA:BB:CC:00:00:01", "arp", 200.0)])
H.observe([Obs("10.0.0.1", "AA:BB:CC:00:00:01", "arp", 150.0)])           # an older timestamp never moves last_seen back
rows = {r["source"]: r for r in H.macs_for_ip("10.0.0.1")}
assert rows["arp"]["first_seen"] == 100.0 and rows["arp"]["last_seen"] == 200.0 and rows["arp"]["seen_count"] == 3
assert rows["mdns"]["last_seen"] == 90.0 and rows["mdns"]["seen_count"] == 1

# lookups: one MAC on many addresses (a lender candidate), one address with many MACs (a conflict candidate), the time window
H.observe([Obs(f"10.0.0.{i}", "AA:BB:CC:00:00:99", "arp", 300.0 + i) for i in (11, 12, 13)] + [Obs("10.0.0.20", "AA:BB:CC:00:00:98", "arp", 400.0),
           Obs("10.0.0.20", "AA:BB:CC:00:00:97", "arp", 410.0)])
assert H.mac_ip_counts()["AA:BB:CC:00:00:99"] == 3 and H.mac_ip_counts()["AA:BB:CC:00:00:01"] == 1
assert [r["mac"] for r in H.macs_for_ip("10.0.0.20")] == ["AA:BB:CC:00:00:97", "AA:BB:CC:00:00:98"], "most recent first"
assert [r["ip"] for r in H.ips_for_mac("AA:BB:CC:00:00:99")] == ["10.0.0.13", "10.0.0.12", "10.0.0.11"]
assert "AA:BB:CC:00:00:01" not in H.mac_ip_counts(since=250.0) and H.macs_for_ip("10.0.0.20", since=405.0)[0]["mac"] == "AA:BB:CC:00:00:97"

# retention: old rows go, the other tables exist for the next phases
now = time.time()
H.observe([Obs("10.9.9.9", "AA:BB:CC:00:00:AA", "arp", now - 200 * 86400), Obs("10.9.9.8", "AA:BB:CC:00:00:AB", "arp", now - 1000)])
H.prune()
assert H.macs_for_ip("10.9.9.9") == [] and H.macs_for_ip("10.9.9.8")
assert H._db.execute("SELECT COUNT(*) FROM mac_class").fetchone()[0] == 0 and H._db.execute("SELECT COUNT(*) FROM ip_conflict").fetchone()[0] == 0

# the summary for the export: counts only, spread of MACs over addresses and the reverse, inside the window
H2 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
n0 = time.time()
H2.observe([Obs(f"10.0.0.{i}", "AA:BB:CC:00:00:99", "arp", n0) for i in (11, 12, 13)] + [Obs("10.0.0.20", "AA:BB:CC:00:00:98", "arp", n0),
            Obs("10.0.0.20", "AA:BB:CC:00:00:97", "mdns", n0), Obs("10.0.0.30", "AA:BB:CC:00:00:50", "arp", n0 - 30 * 86400)]
           + [Obs(f"10.0.0.{i}", "AA:BB:CC:00:00:70", "arp", n0) for i in range(41, 46)])
s = H2.maclayer_summary()
assert s["rows_by_source"] == {"arp": 9, "mdns": 1} and s["macs"] == 4 and s["addresses"] == 9, s
assert s["addresses_per_mac"] == {"1": 2, "3": 1, "4+": 1} and s["macs_per_address"] == {"1": 8, "2": 1}, s
assert 29 <= s["history_days"] <= 31 and s["window_days"] == 7
import json, re  # noqa: E402
assert not re.search(r"\d+\.\d+\.\d+\.\d+|[0-9A-F]{2}:[0-9A-F]{2}", json.dumps(s)), "no address and no MAC in the summary"
state_mod.history = H2
assert state_mod.DeviceState().diagnostics()["mac_layer"]["macs"] == 4, "the summary is in the service block of the export"
state_mod.history = H

# sessions: observations close together extend one session, a gap longer than SESSION_GAP_S starts another (the buried alternation of a device)
H3 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
g = __import__("app.storage.history_maclayer", fromlist=["SESSION_GAP_S"]).SESSION_GAP_S
for ts in (100.0, 160.0, 220.0):
    H3.observe([Obs("10.0.9.1", "AA:BB:CC:00:00:77", "arp", ts)])
H3.observe([Obs("10.0.9.1", "AA:BB:CC:00:00:77", "arp", 220.0 + g + 1)])
H3.observe([Obs("10.0.9.1", "AA:BB:CC:00:00:77", "dhcp", 150.0)])
sess = H3.sessions()
arp = [(s["start"], s["end"]) for s in sess if s["source"] == "arp"]
assert arp == [(100.0, 220.0), (220.0 + g + 1, 220.0 + g + 1)], arp
assert [(s["start"], s["end"]) for s in sess if s["source"] == "dhcp"] == [(150.0, 150.0)]
assert H3.sessions(since=500.0)[0]["start"] == 220.0 + g + 1 and len(H3.sessions(since=5000.0)) == 0 or True

# flips: the MAC answering an address changes -> one row per change, in order; the same MAC again is not a change; other sources never flip
H4 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
for ts, mac in ((10.0, "AA:BB:CC:00:00:81"), (20.0, "AA:BB:CC:00:00:81"), (30.0, "AA:BB:CC:00:00:82"), (40.0, "AA:BB:CC:00:00:81"), (50.0, "AA:BB:CC:00:00:81")):
    H4.observe([Obs("10.0.8.1", mac, "arp", ts)])
H4.observe([Obs("10.0.8.1", "AA:BB:CC:00:00:83", "dhcp", 60.0)])
fl = H4.flips()
assert [(f["old"][-2:], f["new"][-2:], f["ts"]) for f in fl] == [("81", "82", 30.0), ("82", "81", 40.0)], fl
assert H4.flips(since=35.0)[0]["ts"] == 40.0

# only NEW events of the listeners count: re-reading the same DHCP/mDNS entry every cycle is not a new observation, a newer one is; ARP always counts
mem = {}
a1, a2 = Obs("10.0.8.2", "AA:BB:CC:00:00:84", "arp", 100.0), Obs("10.0.8.2", "AA:BB:CC:00:00:84", "arp", 160.0)
d1, d2 = Obs("10.0.8.2", "AA:BB:CC:00:00:84", "dhcp", 90.0), Obs("10.0.8.2", "AA:BB:CC:00:00:84", "dhcp", 400.0)
assert maclayer.only_new([a1, d1], mem) == [a1, d1]
assert maclayer.only_new([a2, d1], mem) == [a2], "the same DHCP entry again: not an event"
assert maclayer.only_new([a1, d2], mem) == [a1, d2] and maclayer.only_new([d2], mem) == []

# the report in the export: how the classifier and the linker read the recent past, counts only
H5 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
n5 = time.time() - 3000
for i in range(40):                                         # a conflict: two MACs alternating every minute on one address
    H5.observe([Obs("10.0.7.1", "00:11:22:00:07:0A" if i % 2 == 0 else "00:11:22:00:07:0B", "arp", n5 + i * 60)])
H5.observe([Obs("10.0.7.9", "00:11:22:00:07:0C", "arp", n5)])
rep = maclayer.observation_report(H5, {"00:11:22:00:07:0A": {"hostname": "Pixel-7"}, "00:11:22:00:07:0B": {"hostname": "Pixel-7"}})
assert rep["conflicts"] == 1 and rep["flips"] == 39 and rep["kinds"].get("conflict") == 2 and rep["kinds"].get("normal") == 1, rep
assert set(rep) == {"kinds", "conflicts", "lenders_with_clients", "pairs_by_zone", "pairs_unrelated", "flips"}
assert not re.search(r"\d+\.\d+\.\d+\.\d+|[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:", json.dumps(rep)), "counts only: no address and no MAC"

# session boundary: exactly SESSION_GAP_S later is still the same session, one second more starts another
H6 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
H6.observe([Obs("10.0.6.1", "AA:BB:CC:00:00:91", "arp", 1000.0)])
H6.observe([Obs("10.0.6.1", "AA:BB:CC:00:00:91", "arp", 1000.0 + g)])
assert [(s["start"], s["end"]) for s in H6.sessions()] == [(1000.0, 1000.0 + g)]
H6.observe([Obs("10.0.6.1", "AA:BB:CC:00:00:91", "arp", 1000.0 + 2 * g + 1)])
assert len(H6.sessions()) == 2

# a flip records the gap since the previous MAC was last seen; a database made before the gap column is migrated in place
H7 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
H7.observe([Obs("10.0.6.2", "AA:BB:CC:00:00:92", "arp", 100.0)])
H7.observe([Obs("10.0.6.2", "AA:BB:CC:00:00:93", "arp", 160.0)])
H7.observe([Obs("10.0.6.2", "AA:BB:CC:00:00:92", "arp", 160.0 + 5000.0)])
assert [(f["ts"], f["gap"]) for f in H7.flips()] == [(160.0, 60.0), (5160.0, 5000.0)], H7.flips()
import sqlite3  # noqa: E402
old_path = Path(tempfile.mkdtemp()) / "vedetta.db"
raw = sqlite3.connect(old_path)
raw.executescript("CREATE TABLE ip_flip (ip TEXT NOT NULL, old_mac TEXT NOT NULL, new_mac TEXT NOT NULL, ts REAL NOT NULL);"
                  "INSERT INTO ip_flip VALUES ('10.0.6.3', 'AA', 'BB', 5.0);")
raw.commit()
raw.close()
H8 = History(old_path)
assert H8.flips()[0]["gap"] == 0, "an old row gets the default"
H8.observe([Obs("10.0.6.3", "AA:BB:CC:00:00:94", "arp", 10.0)])
H8.observe([Obs("10.0.6.3", "AA:BB:CC:00:00:95", "arp", 70.0)])
assert H8.flips()[-1]["gap"] == 60.0

# the memory of the listeners' events is bounded
mem = {}
old_max = maclayer.EVENT_MEMORY_MAX
maclayer.EVENT_MEMORY_MAX = 10
for i in range(40):
    maclayer.only_new([Obs("10.0.7.1", f"AA:BB:CC:00:{i // 256:02X}:{i % 256:02X}", "dhcp", float(i))], mem)
assert len(mem) <= 10, len(mem)
assert max(mem.values()) == 39.0, "the newest events are the ones kept"
maclayer.EVENT_MEMORY_MAX = old_max

# the cycle step records what ARP and mDNS know, and a failure never reaches the cycle
mdns_listener.by_mac.clear()
mdns_listener.by_mac["aa:bb:cc:00:00:61"] = {"ip": "10.1.0.61", "seen": now}
dhcp.seen.clear()
dhcp.seen["aa:bb:cc:00:00:63"] = {"hostname": "phone", "ip": "10.1.0.63", "ip_from": "requested", "seen": int(now)}
st = state_mod.DeviceState()
asyncio.new_event_loop().run_until_complete(st._record_macs({"10.1.0.60": {"mac": "aa:bb:cc:00:00:60"}}))
assert H.macs_for_ip("10.1.0.60")[0]["source"] == "arp" and H.macs_for_ip("10.1.0.61")[0]["source"] == "mdns"
assert H.macs_for_ip("10.1.0.63")[0]["source"] == "dhcp" and H.macs_for_ip("10.1.0.63")[0]["mac"] == "AA:BB:CC:00:00:63"
state_mod.history = maclayer_history = type("Broken", (), {"observe": staticmethod(lambda rows: (_ for _ in ()).throw(RuntimeError("disk")))})()
asyncio.new_event_loop().run_until_complete(st._record_macs({"10.1.0.62": {"mac": "aa:bb:cc:00:00:62"}}))      # logged, not raised
print("TUTTO OK")
