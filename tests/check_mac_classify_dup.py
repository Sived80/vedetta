"""Single MAC layer, the second answer to the same ARP question (1.0 step P3, G2). arp-scan prints every answer to "who has this address?" (the DUP lines
of RFC 5227 conflicts); the view used to keep only the first, so a conflict where the same device always answers first was never seen by the judge.
Now parse_arp_scan keeps the other MACs that answered (`also`), maclayer.from_arp turns them into observations of source "arp_dup" (not "arp": the
changes of the MAC answering an address, ip_flip, stay as they were) and macclassify counts them as ARP answers:
  * two MACs seen TOGETHER at an address (one answering first, the other second) over at least two full sweeps of the network are a conflict, with no
    alternation at all;
  * a MAC that answers second at three addresses at once is a lender (an ARP proxy): what the old filter of one scan did (#9), now judged in time;
  * the repeater of the simulator's S4 lends its MAC to its clients: no conflict.
Observations go through the real store (History.observe), one ARP view every two minutes; every address and MAC is made up."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import arpview, macclassify, maclayer  # noqa: E402
from app.scan import scan_arp  # noqa: E402
from app.storage.history import History  # noqa: E402

STEP_S = 120
CAM, RELAY, PROXY, REP, C1, C2, C3 = (f"02:00:00:00:40:0{k}" for k in range(1, 8))


def store():
    return History(Path(tempfile.mkdtemp()) / "vedetta.db")


def judge(h, now):
    since = now - 7 * 86400
    sessions, flips = h.sessions(since), h.flips(since)
    res = macclassify.classify(h.rows(since), sessions, flips)
    return res, macclassify.last_evidence(res["conflicts"], sessions, flips)


def view(lines: str) -> dict:
    """The ARP view of one cycle as the app builds it: arp-scan output -> hosts -> {ip: host}."""
    return {h["ip"]: h for h in scan_arp.parse_arp_scan(lines)}


# 0) the parse keeps the other answers, only where there are more, without changing anything else of the host
hosts = scan_arp.parse_arp_scan("10.0.40.5\t02:00:00:00:40:01\tCam\n10.0.40.5\t02:00:00:00:40:02\t(Unknown: locally administered)\n"
                                "10.0.40.5\t02:00:00:00:40:01\tCam\n10.0.40.9\t02:00:00:00:40:03\tX\n10.0.40.5\t02:00:00:00:40:04\tY\n")
assert hosts == [{"ip": "10.0.40.5", "mac": CAM, "vendor": "Cam", "also": [RELAY, "02:00:00:00:40:04"]},
                 {"ip": "10.0.40.9", "mac": PROXY, "vendor": "X"}], hosts
assert maclayer.from_arp(view("10.0.40.5\t02:00:00:00:40:01\tCam\n10.0.40.5\t02:00:00:00:40:02\t-\n"), 5.0) == [
    maclayer.Observation("10.0.40.5", CAM, "arp", 5.0), maclayer.Observation("10.0.40.5", RELAY, "arp_dup", 5.0)]

# ... the two cases the parse used to judge by itself in one scan (check_netinfo.py before P3): now it only lists what answered, the judge decides in time
hosts = scan_arp.parse_arp_scan("192.0.2.5\taa:aa:aa:aa:aa:01\tX\n192.0.2.5\taa:aa:aa:aa:aa:02\tY\n192.0.2.9\tbb:bb:bb:bb:bb:01\tZ\n")
assert [(h["ip"], h.get("also")) for h in hosts] == [("192.0.2.5", ["AA:AA:AA:AA:AA:02"]), ("192.0.2.9", None)], hosts
hosts = scan_arp.parse_arp_scan("192.0.2.5\tcc:cc:cc:cc:cc:01\t-\n192.0.2.5\tcc:cc:cc:cc:cc:02\t-\n192.0.2.6\tcc:cc:cc:cc:cc:02\t-\n")
assert [(h["ip"], h["mac"], h.get("also")) for h in hosts] == [("192.0.2.5", "CC:CC:CC:CC:CC:01", ["CC:CC:CC:CC:CC:02"]), ("192.0.2.6", "CC:CC:CC:CC:CC:02", None)]
assert not hasattr(scan_arp, "arp_conflicts"), "no snapshot of the last scan: an ARP proxy is told apart in time (case 2)"

# 1) the camera always answers first, the relay second (it is slower): the first answer never changes, the two are seen together -> conflict
IP = "10.0.40.52"
both = f"{IP}\t{CAM}\tCam\n{IP}\t{RELAY}\tRelay\n"
h, t = store(), 1_800_000_000.0
for _ in range(30):
    h.observe(maclayer.from_arp(view(both), t))
    t += STEP_S
assert h.flips() == [], "the first answer never changes: no flip, the alternation rule alone would never see it"
res, ev = judge(h, t)
assert res["conflicts"] == [{"ip": IP, "macs": [CAM, RELAY]}] and res["macs"][RELAY]["kind"] == "conflict", res
assert ev[0]["last_evidence"] == t - STEP_S, "the last time both answered"

# ... but together only within one full sweep (the view keeps a sweep until the next one) is not enough: two full sweeps are needed
assert macclassify.CONFLICT_MIN_TOGETHER_S == arpview.FULL_SWEEP_S >= macclassify.CONFLICT_MIN_OVERLAP_S
h, t = store(), 1_800_000_000.0
for k in range(30):
    h.observe(maclayer.from_arp(view(both if k < 2 else f"{IP}\t{CAM}\tCam\n"), t))
    t += STEP_S
assert judge(h, t)[0]["conflicts"] == [], "seen together for 2 minutes: one sweep, not two"
h, t = store(), 1_800_000_000.0
for k in range(30):
    h.observe(maclayer.from_arp(view(both if k < 4 else f"{IP}\t{CAM}\tCam\n"), t))
    t += STEP_S
assert judge(h, t)[0]["conflicts"] == [{"ip": IP, "macs": [CAM, RELAY]}], "together for 6 minutes: two sweeps"

# 2) an ARP proxy (a router answering for others) answers second at three addresses: a lender, never a conflict (the old filter #9, in time)
h, t = store(), 1_800_000_000.0
proxied = "".join(f"10.0.40.{i}\t{dev}\tD\n10.0.40.{i}\t{PROXY}\tRouter\n" for i, dev in ((21, C1), (22, C2), (23, C3))) + f"10.0.40.1\t{PROXY}\tRouter\n"
for _ in range(30):
    h.observe(maclayer.from_arp(view(proxied), t))
    t += STEP_S
res, _ = judge(h, t)
assert res["macs"][PROXY]["kind"] == "lender" and res["conflicts"] == [] and res["possible_conflicts"] == [], res

# 3) the repeater of S4: it answers with its own MAC for three clients behind it (and for itself); a client's own MAC also answers one of them
h, t = store(), 1_800_000_000.0
lent = f"10.0.40.30\t{REP}\tRep\n10.0.40.31\t{REP}\tRep\n10.0.40.32\t{REP}\tRep\n10.0.40.33\t{REP}\tRep\n10.0.40.31\t{C1}\tPhone\n"
for _ in range(30):
    h.observe(maclayer.from_arp(view(lent), t))
    t += STEP_S
res, _ = judge(h, t)
assert res["macs"][REP]["kind"] == "lender" and res["conflicts"] == [] and res["possible_conflicts"] == [], res

# 4) a conflict that alternates AND shows both answers: one conflict, dated by the later of the two kinds of evidence
h, t = store(), 1_800_000_000.0
for k in range(30):
    first, second = (CAM, RELAY) if k % 2 else (RELAY, CAM)
    h.observe(maclayer.from_arp(view(f"{IP}\t{first}\tA\n{IP}\t{second}\tB\n"), t))
    t += STEP_S
res, ev = judge(h, t)
assert res["conflicts"] == [{"ip": IP, "macs": [CAM, RELAY]}] and ev[0]["last_evidence"] == t - STEP_S
print("TUTTO OK")
