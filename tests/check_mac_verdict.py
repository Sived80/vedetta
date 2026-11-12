"""Single MAC layer, the verdict in the shadow (1.0 step P1): every cycle the classifier reads the recent window of ip_mac and its verdict is stored in
mac_class and ip_conflict. Proved here: what is stored and how it moves from one cycle to the next, that a failure never reaches the cycle, that the
masked export keeps no address and no MAC of it, and - with a spy on the database and on the source - that one single function writes the two tables
and one single step of the cycle calls it. Since step P2 mac_class has one reader (tests/check_mac_verdict_readers.py); since step P3 ip_conflict has
one reader too: the writer stores the last evidence of each conflict (macclassify.last_evidence), History.ip_conflicts reads the ones going on into
macverdict, and only there a conflict is "going on" (last evidence younger than macverdict.CONFLICT_OPEN_S)."""
import asyncio
import inspect
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import maclayer, macverdict, state as state_mod  # noqa: E402
from app.export.anonymize import Anonymizer  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage.history import History  # noqa: E402

APP = Path(__file__).resolve().parent.parent / "vedetta" / "app"
Obs = maclayer.Observation
A, B, N, L = "00:11:22:00:07:0A", "00:11:22:00:07:0B", "00:11:22:00:07:0C", "00:11:22:00:07:0D"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def mac_class(h):
    return {m: (k, json.loads(d), u) for m, k, d, u in h._db.execute("SELECT mac, kind, detail, updated FROM mac_class")}


def q(h, sql):
    return [tuple(r) for r in h._db.execute(sql)]


def conflicts(h):
    return {(ip, macs): (f, last) for ip, macs, f, last in h._db.execute("SELECT ip, macs, first_seen, last_seen FROM ip_conflict")}


mdns_listener.by_mac.clear()
dhcp.seen.clear()

# a network seen for the last hour: a conflict (two MACs alternating every minute on one address), a normal host, a MAC answering three addresses at once
H = History(Path(tempfile.mkdtemp()) / "vedetta.db")
t0 = time.time() - 3000
for i in range(40):
    H.observe([Obs("10.0.7.1", A if i % 2 == 0 else B, "arp", t0 + i * 60), Obs("10.0.7.9", N, "arp", t0 + i * 60)]
              + [Obs(f"10.0.7.{20 + k}", L, "arp", t0 + i * 60) for k in range(3)])
assert mac_class(H) == {} and conflicts(H) == {}, "observing alone writes no verdict"

# the verdict of one cycle: one row per MAC of the window, the contested address once
t1 = t0 + 3000
assert run(maclayer.store_verdict(H, now=t1)) is None, "the verdict is stored, never handed back to the cycle"
got = mac_class(H)
assert {m: v[0] for m, v in got.items()} == {A: "conflict", B: "conflict", N: "normal", L: "lender"}, got
assert got[L][1] == {"ips": ["10.0.7.20", "10.0.7.21", "10.0.7.22"], "behind": []} and got[N][1] == {"ips": ["10.0.7.9"], "behind": []}
assert all(v[2] == t1 for v in got.values())
assert conflicts(H) == {("10.0.7.1", f"{A},{B}"): (t1, t1)}, conflicts(H)
assert got == {m: (v["kind"], {"ips": v["ips"], "behind": v["behind"]}, t1) for m, v in maclayer.verdict(H, now=t1)["macs"].items()}, \
    "the stored verdict is the classifier's own, nothing added"

# the next cycle: an unchanged verdict is not written again (updated = since when it holds), the conflict keeps its start and moves its end
t2 = t1 + 60
run(maclayer.store_verdict(H, now=t2))
assert mac_class(H) == got, "same verdict: same rows, same time"
assert conflicts(H) == {("10.0.7.1", f"{A},{B}"): (t1, t2)}
H.observe([Obs("10.0.7.23", N, "arp", t2), Obs("10.0.7.9", N, "arp", t2)])          # the normal host now answers two addresses at once
run(maclayer.store_verdict(H, now=t2 + 1))
after = mac_class(H)
assert after[N][0] == "multi_address" and after[N][2] == t2 + 1 and after[A] == got[A], after

# a MAC that left the window has no verdict any more; the conflict stays recorded (the retention of the MAC layer removes it later)
H.observe([Obs("10.0.7.9", N, "arp", t2 + 8 * 86400)])
run(maclayer.store_verdict(H, now=t2 + 8 * 86400))
assert set(mac_class(H)) == {N}, mac_class(H)
assert ("10.0.7.1", f"{A},{B}") in conflicts(H)

# the cycle step: recording the observations of a cycle also stores the verdict of the window
H2 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
state_mod.history = H2
run(state_mod.DeviceState()._record_macs({"10.0.8.1": {"mac": "00:11:22:00:08:01"}}))
assert mac_class(H2)["00:11:22:00:08:01"][0] == "normal"


# a failure of the verdict never reaches the cycle, and never stops the observations from being recorded
class NoVerdict(History):
    def store_mac_verdict(self, verdict, now):
        raise RuntimeError("disk")


H3 = NoVerdict(Path(tempfile.mkdtemp()) / "vedetta.db")
run(maclayer.record({"10.0.8.2": {"mac": "00:11:22:00:08:02"}}, H3))                  # logged, not raised
assert H3.macs_for_ip("10.0.8.2") and mac_class(H3) == {}
broken = type("Broken", (), {"observe": staticmethod(lambda rows: 0), "rows": staticmethod(lambda since: 1 / 0)})()
run(maclayer.record({"10.0.8.3": {"mac": "00:11:22:00:08:03"}}, broken))             # logged, not raised

# the export masks every text of the database: no address and no MAC of the verdict is left
anon = Anonymizer()
for (_, _, detail, _) in H._db.execute("SELECT * FROM mac_class").fetchall():
    masked = anon.text(detail)
    assert not any(x in masked for x in (A, B, N, L, A.lower(), "10.0.7.9", "10.0.7.20", "10.0.7.23")), masked
assert all(anon.text(macs) != macs for (macs,) in H._db.execute("SELECT macs FROM ip_conflict"))

# --- step P3: the last evidence of each conflict is stored by the writer and read back into macverdict, where only the ones going on are given
H5 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
t5 = time.time() - 3000
for i in range(40):
    H5.observe([Obs("10.0.7.1", A if i % 2 == 0 else B, "arp", t5 + i * 60), Obs("10.0.7.9", N, "arp", t5 + i * 60)])
evidence = t5 + 39 * 60                                                             # the last change between the two
macverdict.refresh_conflicts([])
run(maclayer.store_verdict(H5, now=t5 + 3000))
assert maclayer.verdict(H5, now=t5 + 3000)["conflicts"] == [{"ip": "10.0.7.1", "macs": [A, B], "last_evidence": evidence}]
assert q(H5, "SELECT last_evidence FROM ip_conflict") == [(evidence,)]
assert macverdict.conflicts(t5 + 3000) == {"10.0.7.1": [A, B]}, "the cycle fills the conflicts going on"
assert macverdict.conflicts(evidence + macverdict.CONFLICT_OPEN_S) == {"10.0.7.1": [A, B]}
assert macverdict.conflicts(evidence + macverdict.CONFLICT_OPEN_S + 1) == {}, "no evidence for longer than CONFLICT_OPEN_S: over"
assert macverdict.CONFLICT_OPEN_S == 20 * 60, "decided 12/11: 20 minutes, over twice the longest gap seen on a real network"
H5.observe([Obs("10.0.7.1", A, "arp", t5 + 3000 + k * 60) for k in range(30)])    # the second device is gone: the evidence stays where it was
run(maclayer.store_verdict(H5, now=t5 + 4800))
assert q(H5, "SELECT first_seen, last_seen, last_evidence FROM ip_conflict") == [(t5 + 3000, t5 + 4800, t5 + 3000)], \
    "the camera took the address back once more at the first view without the relay: that change is the last evidence"
assert macverdict.conflicts(t5 + 3000 + macverdict.CONFLICT_OPEN_S + 1) == {}, "still a conflict for the seven days of the verdict, but over"
# at start the conflicts going on of the last run are read back; a failure keeps the last ones
macverdict.refresh_conflicts([{"ip": "10.0.7.1", "macs": [A, B], "first_seen": 0.0, "last_evidence": time.time()}])


class NoConflicts(History):
    def ip_conflicts(self, since):
        raise RuntimeError("disk")


maclayer.load_verdict(NoConflicts(Path(tempfile.mkdtemp()) / "vedetta.db"))
assert macverdict.conflicts(time.time()) == {"10.0.7.1": [A, B]}, "a failed read keeps the last conflicts"
H6 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
for i in range(40):
    H6.observe([Obs("10.0.7.3", A if i % 2 == 0 else B, "arp", time.time() - 2400 + i * 60)])
run(maclayer.store_verdict(H6))
macverdict.refresh_conflicts([])
maclayer.load_verdict(H6)
assert macverdict.conflicts(time.time()) == {"10.0.7.3": [A, B]}, "the conflict going on before a restart is there at once"
# three MACs on one address are one entry, every MAC once; a conflict with no evidence at all is not going on
macverdict.refresh_conflicts([{"ip": "10.0.7.4", "macs": [A, B], "first_seen": 0.0, "last_evidence": 100.0},
                              {"ip": "10.0.7.4", "macs": [A, N], "first_seen": 0.0, "last_evidence": 90.0},
                              {"ip": "10.0.7.5", "macs": [A, L], "first_seen": 0.0, "last_evidence": None}])
assert macverdict.conflicts(100.0) == {"10.0.7.4": [A, B, N]}, macverdict.conflicts(100.0)

# an old database (ip_conflict without the column) gets it on open, and the writer fills it
old = Path(tempfile.mkdtemp()) / "vedetta.db"
db = sqlite3.connect(old)
db.execute("CREATE TABLE ip_conflict (ip TEXT NOT NULL, macs TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL, PRIMARY KEY (ip, macs))")
db.execute("INSERT INTO ip_conflict VALUES ('10.0.7.1', ?, 1.0, 2.0)", (f"{A},{B}",))
db.commit()
db.close()
H7 = History(old)
assert "last_evidence" in [r[1] for r in H7._db.execute("PRAGMA table_info(ip_conflict)")]
for i in range(40):
    H7.observe([Obs("10.0.7.1", A if i % 2 == 0 else B, "arp", t5 + i * 60)])
run(maclayer.store_verdict(H7, now=t5 + 3000))
assert q(H7, "SELECT first_seen, last_seen, last_evidence FROM ip_conflict") == [(1.0, t5 + 3000, evidence)]
assert all(anon.text(macs) != macs for (macs,) in H7._db.execute("SELECT macs FROM ip_conflict")), "the export masks it as before"

# SPY on the database: every statement that changes mac_class or ip_conflict, and the function that issued it, over cycles and the retention
H4 = History(Path(tempfile.mkdtemp()) / "vedetta.db")
WRITES: list = []
CHANGE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b[^;]*\b(mac_class|ip_conflict)\b", re.IGNORECASE)
READ = re.compile(r"^\s*SELECT\b[^;]*\bFROM\s+ip_conflict\b", re.IGNORECASE)
READERS: list = []


def spy(sql):
    if READ.search(sql):
        names = [f.function for f in inspect.stack()[1:]]
        READERS.append("ip_conflicts" if "ip_conflicts" in names else names[0])
    if CHANGE.search(sql):
        names = [f.function for f in inspect.stack()[1:]]     # who issued it: the writer (through its helpers) or someone else
        WRITES.append((next((n for n in names if n in ("store_mac_verdict", "prune_maclayer")), names[0]), sql.split()[0].upper()))


H4._db.set_trace_callback(spy)
state_mod.history = H4
st = state_mod.DeviceState()
t4 = time.time()
for i in range(12):
    arp = {"10.0.9.1": {"mac": A if i % 2 == 0 else B}, "10.0.9.2": {"mac": N}}
    H4.observe([Obs("10.0.9.1", A if i % 2 == 0 else B, "arp", t4 - 3000 + i * 60)])
    run(st._record_macs(arp))
H4.prune()
writers = {w for w, _ in WRITES}
assert WRITES and {k for _, k in WRITES} >= {"INSERT"}, "the spy sees the writes (a spy that sees nothing proves nothing)"
assert writers <= {"store_mac_verdict", "prune_maclayer"}, writers
assert all(w == "store_mac_verdict" or k == "DELETE" for w, k in WRITES), "the retention only deletes old rows"
maclayer.load_verdict(H4)
assert READERS and set(READERS) == {"ip_conflicts"}, "every read of ip_conflict is History.ip_conflicts: " + repr(set(READERS))

# SPY on the source: the SQL on the two tables lives in one file, one function writes them, one step of the cycle calls it, one reader each
SQL_ON = re.compile(r"\b(FROM|INTO|UPDATE|TABLE|JOIN)\s+(mac_class|ip_conflict)\b", re.IGNORECASE)
sql_files, callers, steps, conflict_readers, conflict_refreshers = set(), [], [], [], []
for f in APP.rglob("*.py"):
    text = f.read_text(encoding="utf-8")
    rel = f.relative_to(APP).as_posix()
    if SQL_ON.search(text):
        sql_files.add(rel)
    callers += [rel for _ in re.finditer(r"\.store_mac_verdict\(", text)]
    steps += [rel for _ in re.finditer(r"(?<!def )\bstore_verdict\(", text)]
    conflict_readers += [rel for _ in re.finditer(r"\.ip_conflicts\(", text)]
    conflict_refreshers += [rel for _ in re.finditer(r"macverdict\.refresh_conflicts\(", text)]
assert sql_files == {"storage/history_maclayer.py"}, sql_files
assert callers == ["maclayer.py"], "one function writes the verdict: " + repr(callers)
assert steps == ["maclayer.py"], "maclayer.record is the only step that stores the verdict: " + repr(steps)
reads = re.findall(r"SELECT[^\"']*\bFROM\s+(mac_class|ip_conflict)\b", (APP / "storage" / "history_maclayer.py").read_text(encoding="utf-8"), re.IGNORECASE)
assert reads == ["mac_class", "mac_class", "ip_conflict"], "the writer's own comparison, the one reader of mac_class (P2) and the one of ip_conflict (P3): " + repr(reads)
assert conflict_readers == ["maclayer.py"], "History.ip_conflicts has one caller: " + repr(conflict_readers)
assert conflict_refreshers == ["maclayer.py"], "only maclayer fills the conflicts of macverdict: " + repr(conflict_refreshers)
print("TUTTO OK")
