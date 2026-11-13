"""The card -> MAC link, stored in the shadow (1.0 step P4): the table card_mac, its one writer and its one reader, and the step of the cycle that
fills it (cardlink_cycle.update, run by maclayer.record after the verdict, at most every FULL_SWEEP_S). Proved here: the schema on an old
database, the rows written and deleted as the rule says (seed at the first judgement, rule after), the retention never touching the table, a
failure never reaching the cycle, the export masking every MAC and address of it, the counts of the export, and - with a spy on the database and
on the source - that one function writes the table, one reads it, and no file that decides anything names it."""
import asyncio
import inspect
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink_cycle, linkview, maclayer, macverdict, netutil  # noqa: E402
from app.export import anonymize, export_mask  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

APP = Path(__file__).resolve().parent.parent / "vedetta" / "app"
Obs = maclayer.Observation
A, B, C, L = "02:00:00:00:60:0A", "02:00:00:00:60:0B", "02:00:00:00:60:0C", "02:00:00:00:60:01"
NET = "10.0.60.0/24"


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def rows(h):
    return {r[0]: r[1:] for r in h._db.execute("SELECT device_id, seq, network, mac, state, reason, source, ip FROM card_mac")}


def write_cards(cards):
    devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": cards}), encoding="utf-8")


def cardd(seq, last, **kw):
    return {"id": f"scan-10-0-60-{last}", "ip": f"10.0.60.{last}", "name": f"Card {last}", "seq": seq, **kw}


def network(h, t0, minutes=20, extra=()):
    """A minute-by-minute ARP view: A and B on their addresses, a repeater lending its MAC on three addresses."""
    for i in range(minutes):
        t = t0 + i * 60
        h.observe([Obs("10.0.60.11", A, "arp", t), Obs("10.0.60.12", B, "arp", t)] + [Obs(f"10.0.60.{20 + k}", L, "arp", t) for k in range(3)]
                  + [Obs(ip, m, "arp", t) for ip, m in extra])


mdns_listener.by_mac.clear()
dhcp.seen.clear()
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
netutil.last_network = NET
maclayer.after_verdict(cardlink_cycle.update)
maclayer.after_verdict(cardlink_cycle.update)
assert maclayer._after_verdict == [cardlink_cycle.update], "registered once, however many times start runs"

# an old database (made before the table existed) gets it on open
old = tmp / "old.db"
db = sqlite3.connect(old)
db.execute("CREATE TABLE ip_mac (ip TEXT NOT NULL, mac TEXT NOT NULL, source TEXT NOT NULL, first_seen REAL NOT NULL, last_seen REAL NOT NULL, "
            "seen_count INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (ip, mac, source))")
db.commit()
db.close()
H = History(old)
cols = [r[1] for r in H._db.execute("PRAGMA table_info(card_mac)")]
assert cols == ["device_id", "seq", "network", "mac", "state", "reason", "source", "ip", "since", "changed"], cols

# the first judgement after the upgrade: the seed. Two steady devices linked, the repeater's card not (its MAC is lent)
now = time.time()
network(H, now - 1200)
write_cards([cardd(1, 11), cardd(2, 12), cardd(3, 20)])
cardlink_cycle._last = 0.0
run(maclayer.record({}, H))
assert macverdict.kind(L) == "lender"
assert rows(H) == {"scan-10-0-60-11": (1, "main", A, "linked", None, "seed", "10.0.60.11"),
                   "scan-10-0-60-12": (2, "main", B, "linked", None, "seed", "10.0.60.12")}, rows(H)
assert cardlink_cycle.counts(H) == {"linked": 2, "held": {}, "unlinked": {"shared_kind": 1}, "source": {"seed": 2}}, cardlink_cycle.counts(H)

# at most every FULL_SWEEP_S: a card removed meanwhile keeps its row until the next judgement
write_cards([cardd(1, 11), cardd(3, 20), cardd(4, 13)])
network(H, now - 1200, extra=[("10.0.60.13", C)])
run(maclayer.store_verdict(H))
run(cardlink_cycle.update(H, now=now + 10))
assert set(rows(H)) == {"scan-10-0-60-11", "scan-10-0-60-12"}, "not judged again within FULL_SWEEP_S"
# the next judgement: the removed card's row is deleted, the card added later is linked by the rule
run(cardlink_cycle.update(H, now=now + 400))
got = rows(H)
assert set(got) == {"scan-10-0-60-11", "scan-10-0-60-13"} and got["scan-10-0-60-13"][2:6] == (C, "linked", None, "rule"), got

# the same id given to another card (removed, then added again: a new seq) never inherits the link
write_cards([cardd(5, 11), cardd(3, 20), cardd(4, 13)])
run(cardlink_cycle.update(H, now=now + 800))
assert "scan-10-0-60-11" not in rows(H)
run(cardlink_cycle.update(H, now=now + 1200))
assert rows(H)["scan-10-0-60-11"][:6] == (5, "main", A, "linked", None, "rule"), "the new card is judged by itself"

# the retention never touches the table: a link does not expire with time
H._db.execute("UPDATE card_mac SET since = 1.0, changed = 1.0")
H._db.commit()
before = rows(H)
H.prune()
H.prune_maclayer()
assert rows(H) == before

# the export masks every MAC and address of the table
copy = tmp / "export.db"
dst = sqlite3.connect(copy)
H._db.backup(dst)                                             # a consistent copy, as the export makes it
dst.close()
export_mask._mask_db(copy, anonymize.Anonymizer())
masked = sqlite3.connect(copy).execute("SELECT * FROM card_mac").fetchall()
assert masked and not any(x in str(masked) for x in (A, B, C, A.lower(), "10.0.60.11", "10.0.60.13")), masked


# a failure never reaches the cycle, and never stops the verdict
class NoStore(History):
    def store_card_links(self, write, delete, seeded):
        raise RuntimeError("disk")


H3 = NoStore(tmp / "h3.db")
network(H3, now - 1200)
cardlink_cycle._last = 0.0
run(maclayer.record({}, H3))                                  # logged, not raised
assert rows(H3) == {} and H3.mac_kinds()
broken = type("Broken", (), {"card_links": staticmethod(lambda: 1 / 0)})()
run(cardlink_cycle.update(broken, now=now + 5000))           # logged, not raised
assert cardlink_cycle.counts(broken) is None
netutil.last_network = None
cardlink_cycle._last = 0.0
run(cardlink_cycle.update(H, now=now + 6000))                # the main network not read yet: nothing judged, nothing written
assert cardlink_cycle._last == 0.0
netutil.last_network = NET

# the cycle reads the links through linkview (1.0 step P5): filled after every judgement with the rows just stored, and at start from the last run
# (no judgement of the new run has looked at them yet); a failure leaves the answer it had
H._db.execute("UPDATE card_mac SET since = 1.0, changed = 1.0")
H._db.commit()
cardlink_cycle._last = 0.0
run(cardlink_cycle.update(H, now=now + 7000))
assert {d: linkview.row(d) for d in H.card_links()} == H.card_links(), "the rows just stored"
assert linkview.check("scan-10-0-60-13", 4, "main", now + 7000) == (C, "used"), linkview.check("scan-10-0-60-13", 4, "main", now + 7000)
linkview._rows, linkview._judged = {}, None                   # a new run
cardlink_cycle.load(H)
assert linkview.row("scan-10-0-60-13") == H.card_links()["scan-10-0-60-13"]
assert linkview.check("scan-10-0-60-13", 4, "main", now + 7000) == (None, "unjudged"), "read at start, not judged yet in this run"
cardlink_cycle.load(broken)                                  # logged, not raised; the answer stays
assert linkview.row("scan-10-0-60-13") == H.card_links()["scan-10-0-60-13"]
run(cardlink_cycle.update(H, now=now + 7400))
assert linkview.check("scan-10-0-60-13", 4, "main", now + 7400) == (C, "used"), "the first judgement of this run looked at it"
cardlink_cycle._last = 0.0
run(maclayer.record({}, H3))                                 # a judgement that fails to store: the answer stays
assert linkview.check("scan-10-0-60-13", 4, "main", now + 7400) == (C, "used")

# the requests reach the one writer at its next judgement, and are forgotten once written: a release deletes the row (here the rule links the
# card again at once, its history being clean: a new link, which waits two judgements as any other); a relink writes the new MAC, source "user"
run(maclayer.store_verdict(H))                               # the verdict of this database again (the one of H3 was read last)
linkview.release("scan-10-0-60-13")
linkview.relink("scan-10-0-60-11", B)
assert linkview.check("scan-10-0-60-13", 4, "main", now + 7400) == (None, "released")
run(cardlink_cycle.update(H, now=now + 7800))
got = rows(H)
assert got["scan-10-0-60-13"][2:6] == (C, "linked", None, "rule") and H.card_links()["scan-10-0-60-13"]["changed"] == now + 7800, got
assert got["scan-10-0-60-11"] == (5, "main", B, "linked", None, "user", "10.0.60.11"), got
assert linkview.requests() == {} and linkview.check("scan-10-0-60-13", 4, "main", now + 7800) == (None, "young")
run(cardlink_cycle.update(H, now=now + 8200))
assert rows(H)["scan-10-0-60-11"][3:6] == ("linked", None, "user"), "the relinked row is kept as any link"

# the counts of presence by MAC for the export (1.0 step P5): numbers only, next to the counts of the links
pc = cardlink_cycle.presence_counts()
assert set(pc) == {"cycles", "used", "unused", "other_at_address", "found_elsewhere", "moved", "pushed", "two_private"}, pc
assert all(isinstance(v, int) for k, v in pc.items() if k != "unused") and all(isinstance(v, int) for v in pc["unused"].values()), pc
assert len(re.findall(r"cardlink_cycle\.presence_counts\(", (APP / "export" / "export_zip.py").read_text(encoding="utf-8"))) == 1, "the export counts"

# SPY on the database: every statement on card_mac, and the function that issued it, over cycles, a removed card and the retention
H4 = History(tmp / "h4.db")
network(H4, now - 1200)
write_cards([cardd(1, 11), cardd(2, 12)])
WRITES, READS = [], []
CHANGE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b[^;]*\bcard_mac\b", re.IGNORECASE)
READ = re.compile(r"^\s*SELECT\b[^;]*\bFROM\s+card_mac\b", re.IGNORECASE)


def spy(sql):
    if CHANGE.search(sql) or READ.search(sql):
        names = [f.function for f in inspect.stack()[1:]]
        (WRITES if CHANGE.search(sql) else READS).append(next((n for n in names if n in ("store_card_links", "card_links")), names[0]))


H4._db.set_trace_callback(spy)
for k, cards in enumerate(([cardd(1, 11), cardd(2, 12)], [cardd(1, 11)], [cardd(1, 11), cardd(6, 12)])):
    write_cards(cards)
    cardlink_cycle._last = 0.0
    run(maclayer.record({}, H4))
H4.prune()
H4.prune_maclayer()
cardlink_cycle.counts(H4)
assert WRITES and READS, "the spy sees the statements (a spy that sees nothing proves nothing)"
assert set(WRITES) == {"store_card_links"}, set(WRITES)
assert set(READS) == {"card_links"}, set(READS)

# SPY on the source: the SQL on card_mac lives in one file; one caller of the writer, the reader read by the step and the export count only;
# no file that decides anything (presence, identity_upkeep, probe, state*) names the table or the rule
sql_files, writers, readers, deciders = set(), [], [], []
for f in APP.rglob("*.py"):
    text = f.read_text(encoding="utf-8")
    rel = f.relative_to(APP).as_posix()
    if re.search(r"\b(FROM|INTO|UPDATE|TABLE|JOIN)\s+card_mac\b", text, re.IGNORECASE):
        sql_files.add(rel)
    writers += [rel for _ in re.finditer(r"\.store_card_links\(", text)]
    readers += [rel for _ in re.finditer(r"\.card_links\(", text)]
    if re.match(r"(.*/)?(presence|identity_upkeep|probe|state)", rel) and re.search(r"card_mac|cardlink", text):
        deciders.append(rel)
assert sql_files == {"storage/history_maclayer.py"}, sql_files
assert writers == ["cardlink_cycle.py"], writers
assert set(readers) == {"cardlink_cycle.py"} and len(readers) == 4, "the step's comparison, the reading back for linkview, at start, the export count: " + repr(readers)
assert deciders == [], "they read the links through linkview: " + repr(deciders)
importers = sorted(f.relative_to(APP).as_posix() for f in APP.rglob("*.py") if re.search(r"\bimport\b[^\n]*\blinkview\b", f.read_text(encoding="utf-8")))
assert "cardlink_cycle.py" in importers and set(importers) <= {"state_cycle.py", "cardlink_cycle.py", "identity_upkeep.py"}, importers
assert len(re.findall(r"cardlink_cycle\.load\b", (APP / "main.py").read_text(encoding="utf-8"))) == 1, "linkview filled at start"
assert len(re.findall(r"cardlink_cycle\.counts\(", (APP / "export" / "export_zip.py").read_text(encoding="utf-8"))) == 1, "the export counts"
print("TUTTO OK")
