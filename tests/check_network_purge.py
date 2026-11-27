# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""«Delete and start from scratch» of a written network (networks/purge.py and History.purge_network): everything Vedetta knows of that network
goes, nothing of another network is touched.
Two networks behind the router, A (192.168.60.0/24) and B (192.168.70.0/24), and the main one: cards in all three, an adopted device of Home
Assistant in A and in B, rows in every table of the history (presence, scans, response times, MAC memory and changes, card links, known MACs,
ip_mac with its sessions, flips and conflicts, the blocks asked, the addresses of the ping sweep behind the router). 1) the preview counts the cards of A, the devices seen in A and the rows of A; 2) the purge
of A: its row in networks.json, its cards, its adopted device and every row of A are gone; 3) every row of B and of the main network is exactly
as before (the whole database and the files compared); the ignored devices (ignored.json) by MAC or address of A go, the others and those
ignored by name (they hold for every network) stay; 4) a network no longer written or unknown cannot be purged; 5) the API: GET gives the
counts, POST purges and answers with the list, the main network is a 404.
Invented private addresses only.
    python tests/check_network_purge.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import yaml  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import model, purge, registry  # noqa: E402
from app.routes import network_routes  # noqa: E402
from app.storage import blocklist, devices_config, network_store, passive_store  # noqa: E402
from app.storage.history import history  # noqa: E402

registry.ROUTE_FILE = os.path.join(DATA, "no-route-file")   # the fake network, not the routes of this computer
MAIN = registry.main_network("192.168.50.0/24")
NET = {"A": "192.168.60", "B": "192.168.70", "M": "192.168.50"}
MAC = {"A": "02:00:5e:60:00:%02x", "B": "02:00:5e:70:00:%02x", "M": "02:00:5e:50:00:%02x"}


def ip(net, i):
    return "%s.%d" % (NET[net], i)


def mac(net, i):
    return MAC[net] % i


def fill():
    network_store.add({"id": "neta", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed", "name": "A"}, MAIN)
    network_store.add({"id": "netb", "cidr": "192.168.70.0/24", "via": ["routed"], "state": "confirmed", "name": "B"}, MAIN)
    cards = [{"id": "%s%d" % (n.lower(), i), "name": "%s %d" % (n, i), "ip": ip(n, i), "port": 80} for n in NET for i in (4, 5)]
    devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": cards}), encoding="utf-8")
    passive_store.reset_cache()
    rows = [{"mac": mac(n, 9), "ip": ip(n, 9), "host": None, "name": "ha " + n, "online": True, "since": 1.0} for n in ("A", "B")]
    passive_store.record_read(rows, 100.0)
    passive_store.adopt([r["mac"] for r in rows], 100.0)
    db = history._db
    for n in NET:
        for i in (4, 5, 9):
            did = ("ha-" + mac(n, i).replace(":", "")) if i == 9 else "%s%d" % (n.lower(), i)
            db.execute("INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES (?, ?, ?, 1, ?)", (did, ip(n, i), mac(n, i), 10.0 + i))
            db.execute("INSERT INTO scans (device_id, ts, result_json) VALUES (?, ?, '{}')", (did, 20.0 + i))
            db.execute("INSERT INTO latency (device_id, ts, ms) VALUES (?, ?, 3)", (did, 30.0 + i))
            db.execute("INSERT INTO mac_memory (mac, first_seen, last_seen, device_id, ip) VALUES (?, 1, 2, ?, ?)", (mac(n, i), did, ip(n, i)))
            db.execute("INSERT INTO mac_takeover (ts, device_id, ip, old_mac, new_mac, new_known) VALUES (5, ?, ?, ?, ?, 0)", (did, ip(n, i), mac(n, i), mac(n, i)))
            db.execute("INSERT INTO card_mac (device_id, seq, network, mac, state, source, ip, since, changed) VALUES (?, 1, ?, ?, 'linked', 'arp', ?, 1, 1)",
                       (did, {"A": "neta", "B": "netb", "M": "main"}[n], mac(n, i), ip(n, i)))
        for i in (4, 7):      # 7: a device with no card
            db.execute("INSERT INTO known_macs (mac, first_seen, ip, status) VALUES (?, 1, ?, 'new')", (mac(n, i + 100), ip(n, i)))
            db.execute("INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen) VALUES (?, ?, 'arp', 1, 2)", (ip(n, i), mac(n, i + 100)))
            db.execute("INSERT INTO ip_mac_session (ip, mac, source, start, end) VALUES (?, ?, 'arp', 1, 2)", (ip(n, i), mac(n, i + 100)))
            db.execute("INSERT INTO ip_flip (ip, old_mac, new_mac, ts) VALUES (?, ?, ?, 3)", (ip(n, i), mac(n, i), mac(n, i + 100)))
            db.execute("INSERT INTO ip_conflict (ip, macs, first_seen, last_seen) VALUES (?, ?, 1, 2)", (ip(n, i), mac(n, i) + "," + mac(n, i + 100)))
        db.execute("INSERT INTO scan_blocks (block, ts, found) VALUES (?, 1, 2)", (NET[n] + ".0/24",))
        net_id = {"A": "neta", "B": "netb", "M": "main"}[n]      # the ping sweep behind the router (step P11): one row with a MAC from Home Assistant, one without
        db.execute("INSERT INTO routed_seen (network, ip, first_seen, last_seen, mac, host, status) VALUES (?, ?, 1, 2, ?, NULL, 'new')", (net_id, ip(n, 40), mac(n, 40)))
        db.execute("INSERT INTO routed_seen (network, ip, first_seen, last_seen, mac, host, status) VALUES (?, ?, 1, 2, NULL, NULL, 'known')", (net_id, ip(n, 41)))
    db.commit()
    for kind, value in (("mac", mac("A", 4).upper()), ("ip", ip("A", 7)), ("mac", mac("B", 5).upper()), ("ip", ip("M", 4)), ("name", "phone of a guest"),
                        ("mac", "02:00:5e:99:00:01")):
        blocklist.add(kind, value)


TABLES = ("presence_events", "scans", "latency", "mac_memory", "mac_takeover", "card_mac", "known_macs", "ip_mac", "ip_mac_session", "ip_flip", "ip_conflict",
          "scan_blocks", "meta", "mac_class", "health_finding", "routed_seen")


def snapshot():
    return {t: sorted(json.dumps(dict(r), sort_keys=True) for r in history._db.execute("SELECT * FROM " + t).fetchall()) for t in TABLES}  # noqa: S608


def of_a(row: str) -> bool:
    """A row that belongs to network A: an address of A, a card or device id of A, the network id of A."""
    return NET["A"] + "." in row or '"a4"' in row or '"a5"' in row or "5e6000" in row or "5e:60:" in row or '"neta"' in row


fill()
before = snapshot()
files_before = {"cards": [c for c in devices_config.load_devices() if not c["ip"].startswith(NET["A"])],
                "adopted": [m for m in passive_store.snapshot()["adopted"] if not m.startswith("02:00:5e:60")],
                "networks": [r for r in network_store.rows() if r["id"] != "neta"],
                "ignored": [i for i in blocklist.list_items() if i["value"] not in (mac("A", 4).upper(), ip("A", 7))]}
assert len(blocklist.list_items()) == 6
assert all(any(of_a(r) for r in before[t]) for t in TABLES if t not in ("meta", "mac_class", "health_finding")), "network A has rows in every table"

# 1) the preview
neta = next(n for n in network_store.load(MAIN) if n.id == "neta")
got = purge.preview(neta)
assert got == {"cards": 3, "devices": 6, "rows": 31, "ignored": 2}, got   # two cards and the adopted one; the MACs seen at addresses of A: those three, two without a card
#                                                                           and the one of the ping sweep; rows: 6 tables x 3 cards + 5 tables x 2 addresses + 1 block + 2 rows of
#                                                                           the sweep; ignored: one MAC seen in A, one address of A

# 2) the purge
removed = purge.run(neta)
assert sorted(removed) == sorted(["a4", "a5", "ha-" + mac("A", 9).replace(":", "")]), removed
after = snapshot()
for table in TABLES:
    assert not [r for r in after[table] if of_a(r)], (table, [r for r in after[table] if of_a(r)])

# 3) nothing of B or of the main network changed
for table in TABLES:
    assert after[table] == [r for r in before[table] if not of_a(r)], table
assert devices_config.load_devices() == files_before["cards"]
assert sorted(passive_store.snapshot()["adopted"]) == sorted(files_before["adopted"])
assert network_store.rows() == files_before["networks"]
assert blocklist.list_items() == files_before["ignored"], blocklist.list_items()

# 4) not a network that is not written (the main network has its own purge, of its devices only: tests/check_network_purge_main.py)
for bad in (neta, model.Network("nope", neta.cidr, neta.via, neta.touch, neta.state)):
    try:
        purge.run(bad)
        raise AssertionError("purged " + bad.id)
    except ValueError:
        pass


# 5) the API
async def fake_main():
    return "192.168.50.0/24", "192.168.50.2"


registry.main = fake_main
history.last_presence = lambda: {}
app = FastAPI()
app.include_router(network_routes.router)
c = TestClient(app)
assert c.get("/api/networks/netb/purge").json() == {"cards": 3, "devices": 6, "rows": 31, "ignored": 1}
assert c.get("/api/networks/nope/purge").status_code == 404
r = c.post("/api/networks/netb/purge")
assert r.status_code == 200 and r.json()["networks"] == [] and r.json()["main"]["cards"] == 2, r.text
assert [d["id"] for d in devices_config.load_devices()] == ["m4", "m5"]
print("check_network_purge: ok")
