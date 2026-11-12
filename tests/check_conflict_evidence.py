"""Single MAC layer, when an IP conflict is over (1.0 step P3, G1): the judge looks at seven days, so a conflict that ended stays a conflict for days. What
tells "going on" from "over" is the LAST EVIDENCE: the last time the two MACs really contested the address (the last change of the MAC that answers it
between the two, or the last time both were seen at it together). macclassify.last_evidence finds it, outside classify (the verdict does not change).
The observations go through the real store (History.observe: sessions and flips as the app records them), one ARP view every two minutes; every address
and MAC is made up. A conflict is going on while its last evidence is younger than 20 minutes (decided 12/11; macverdict.CONFLICT_OPEN_S from step 2)."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macclassify  # noqa: E402
from app.maclayer import Observation as Obs  # noqa: E402
from app.storage.history import History  # noqa: E402

OPEN_S = 20 * 60
STEP_S = 120
IP = "10.0.30.52"
CAM, RELAY = "02:00:00:00:30:01", "02:00:00:00:30:02"
GAPS = [3, 4, 3, 3, 4, 3, 4, 3, 3, 4, 3, 3, 4]       # the quiet judgments in a row seen on a real network (01/11 export), longest 4


def store():
    return History(Path(tempfile.mkdtemp()) / "vedetta.db")


def judge(h, now):
    """The verdict of the last seven days and the last evidence of each conflict, as the app would read them at `now`."""
    since = now - 7 * 86400
    sessions, flips = h.sessions(since), h.flips(since)
    res = macclassify.classify(h.rows(since), sessions, flips)
    return res, macclassify.last_evidence(res["conflicts"], sessions, flips)


# 1) the two alternate (the relay answers one view, the camera the next), then the relay leaves: the last evidence is the last change between them
h, t = store(), 1_800_000_000.0
for i in range(20):
    h.observe([Obs(IP, RELAY if i % 2 else CAM, "arp", t)])
    t += STEP_S
for _ in range(30):                                     # an hour of the camera alone
    h.observe([Obs(IP, CAM, "arp", t)])
    t += STEP_S
last_flip = max(f["ts"] for f in h.flips())
assert last_flip == 1_800_000_000.0 + 20 * STEP_S, "the camera took the address back once, at the first view without the relay"
res, ev = judge(h, t)
assert res["conflicts"] == [{"ip": IP, "macs": [CAM, RELAY]}], "seven days of memory: still a conflict for the verdict"
assert ev == [{"ip": IP, "macs": [CAM, RELAY], "last_evidence": last_flip}], ev
assert t - ev[0]["last_evidence"] > OPEN_S, "an hour after the relay left the conflict is over"
assert res["conflicts"] == judge(h, t)[0]["conflicts"] and "last_evidence" not in res["conflicts"][0], "classify itself is unchanged"

# 2) the relay answers only now and then (the gaps of the real network, 3-4 views in a row): once the conflict is certain it is always going on
h, t, open_at = store(), 1_800_000_000.0, None
for gap in GAPS:
    for i in range(5):
        h.observe([Obs(IP, RELAY if i % 2 == 0 else CAM, "arp", t)])
        t += STEP_S
        res, ev = judge(h, t)
        if ev:
            open_at = open_at or t
            assert t - ev[0]["last_evidence"] < OPEN_S, (t, ev)
    for _ in range(gap):
        h.observe([Obs(IP, CAM, "arp", t)])
        t += STEP_S
        res, ev = judge(h, t)
        if open_at:
            assert ev and t - ev[0]["last_evidence"] < OPEN_S, ("a gap of the relay must not end the conflict", t, ev)
assert open_at is not None and open_at - 1_800_000_000.0 <= 3600, "certain within the first hour"

# 3) a device replaced: the old one answers, then the new one takes the address (one change): no conflict, nothing to date
h, t = store(), 1_800_000_000.0
for i in range(60):
    h.observe([Obs(IP, CAM if i < 30 else RELAY, "arp", t)])
    t += STEP_S
res, ev = judge(h, t)
assert res["conflicts"] == [] and ev == [], ev

# 4) a phone whose private MAC rotates on the same address (one MAC after the other, never together): no conflict
h, t = store(), 1_800_000_000.0
rot = [f"06:00:00:00:31:{k:02X}" for k in range(1, 7)]
for k, mac in enumerate(rot):
    for _ in range(40):
        h.observe([Obs(IP, mac, "arp", t)])
        t += STEP_S
res, ev = judge(h, t)
assert res["conflicts"] == [] and ev == [], ev

# 5) pure on its own: the last time both were seen together counts when it is later than the last change; a conflict with no evidence has None
S = [{"ip": IP, "mac": CAM, "source": "arp", "start": 0.0, "end": 5000.0}, {"ip": IP, "mac": RELAY, "source": "arp", "start": 100.0, "end": 4000.0},
     {"ip": IP, "mac": RELAY, "source": "mdns", "start": 0.0, "end": 9000.0}]
F = [{"ip": IP, "old": CAM, "new": RELAY, "ts": 3000.0, "gap": 60.0}, {"ip": "10.0.30.99", "old": CAM, "new": RELAY, "ts": 4500.0, "gap": 0.0}]
C = [{"ip": IP, "macs": [CAM, RELAY]}]
assert macclassify.last_evidence(C, S, F) == [{"ip": IP, "macs": [CAM, RELAY], "last_evidence": 4000.0}], "together until 4000 (mDNS is not an answer)"
assert macclassify.last_evidence(C, S[:1], F[:1])[0]["last_evidence"] == 3000.0
assert macclassify.last_evidence(C, [], [])[0]["last_evidence"] is None
assert C == [{"ip": IP, "macs": [CAM, RELAY]}], "the input is not changed"
print("TUTTO OK")
