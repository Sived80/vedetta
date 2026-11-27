# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""«Delete all the devices» of the main network (networks/purge.py, GET and POST /api/networks/main/purge): the main network is never deleted,
but everything about its devices goes, as for a written network: its cards, the devices of Home Assistant adopted in it, every history row
about it, the ignored entries of it (a MAC seen there, an address of it; those by name stay). The network stays: its name, the written
networks and everything about them are as before. Then Vedetta starts over as at the first install: the next cycle of the new devices is
the starting point (newdevices.BASELINE_KEY gone: what is there is known, no alert), and only a device that comes after it is new.
Invented private addresses only.
    python tests/check_network_purge_main.py"""
import json
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["VEDETTA_DATA_DIR"] = DATA
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import yaml  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.networks import purge, registry  # noqa: E402
from app.routes import network_routes  # noqa: E402
from app.storage import blocklist, devices_config, network_store, newdevices, passive_store  # noqa: E402
from app.storage.history import history  # noqa: E402

registry.ROUTE_FILE = os.path.join(DATA, "no-route-file")   # the fake network, not the routes of this computer
MAIN = registry.main_network("192.168.50.0/24")
NET = {"M": "192.168.50", "A": "192.168.60"}
MAC = {"M": "02:00:5e:50:00:%02x", "A": "02:00:5e:60:00:%02x"}
LINK = {"M": "main", "A": "neta"}


def ip(net, i):
    return "%s.%d" % (NET[net], i)


def mac(net, i):
    return MAC[net] % i


def fill():
    network_store.add({"id": "neta", "cidr": "192.168.60.0/24", "via": ["routed"], "state": "confirmed", "name": "A"}, MAIN)
    network_store.set_main_name("Casa mia")
    cards = [{"id": "%s%d" % (n.lower(), i), "name": "%s %d" % (n, i), "ip": ip(n, i), "port": 80} for n in NET for i in (4, 5)]
    devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": cards}), encoding="utf-8")
    passive_store.reset_cache()
    rows = [{"mac": mac(n, 9), "ip": ip(n, 9), "host": None, "name": "ha " + n, "online": True, "since": 1.0} for n in NET]
    passive_store.record_read(rows, 100.0)
    passive_store.adopt([r["mac"] for r in rows], 100.0)
    db = history._db
    for n in NET:
        for i in (4, 5, 9):
            did = ("ha-" + mac(n, i).replace(":", "")) if i == 9 else "%s%d" % (n.lower(), i)
            db.execute("INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES (?, ?, ?, 1, ?)", (did, ip(n, i), mac(n, i), 10.0 + i))
            db.execute("INSERT INTO card_mac (device_id, seq, network, mac, state, source, ip, since, changed) VALUES (?, 1, ?, ?, 'linked', 'arp', ?, 1, 1)",
                       (did, LINK[n], mac(n, i), ip(n, i)))
        for i in (4, 7):
            db.execute("INSERT INTO known_macs (mac, first_seen, ip, status) VALUES (?, 1, ?, 'known')", (mac(n, i + 100), ip(n, i)))
            db.execute("INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen) VALUES (?, ?, 'arp', 1, 2)", (ip(n, i), mac(n, i + 100)))
        db.execute("INSERT INTO scan_blocks (block, ts, found) VALUES (?, 1, 2)", (NET[n] + ".0/24",))
    db.commit()
    history.meta_set(newdevices.BASELINE_KEY, "1")
    history.meta_set("some_other_value", "kept")
    for kind, value in (("mac", mac("M", 4).upper()), ("ip", ip("M", 7)), ("mac", mac("A", 4).upper()), ("ip", ip("A", 7)), ("name", "phone of a guest")):
        blocklist.add(kind, value)


TABLES = ("presence_events", "card_mac", "known_macs", "ip_mac", "scan_blocks", "meta")


def snapshot():
    return {t: sorted(json.dumps(dict(r), sort_keys=True) for r in history._db.execute("SELECT * FROM " + t).fetchall()) for t in TABLES}  # noqa: S608


def of_main(row: str) -> bool:
    return NET["M"] + "." in row or '"m4"' in row or '"m5"' in row or "5e5000" in row or "5e:50:" in row or '"main"' in row or newdevices.BASELINE_KEY in row


fill()
before = snapshot()
kept = {"cards": [c for c in devices_config.load_devices() if not c["ip"].startswith(NET["M"])],
        "adopted": [m for m in passive_store.snapshot()["adopted"] if not m.startswith("02:00:5e:50")],
        "networks": network_store.rows(), "ignored": [i for i in blocklist.list_items() if i["value"] not in (mac("M", 4).upper(), ip("M", 7))]}


async def fake_main():
    return "192.168.50.0/24", "192.168.50.2"


registry.main = fake_main
history.last_presence = lambda: {}
c = TestClient(FastAPI())
c.app.include_router(network_routes.router)

# 1) the preview of the main network: the same numbers as for a written network
want = {"cards": 3, "devices": 5, "rows": 11, "ignored": 2}       # rows: 2 tables x 3 cards + 2 tables x 2 addresses + 1 block
assert purge.preview(MAIN) == want, purge.preview(MAIN)
assert c.get("/api/networks/main/purge").json() == want
assert snapshot() == before, "a preview deletes nothing"

# 2) the purge: every device of the main network goes, the network stays
r = c.post("/api/networks/main/purge")
assert r.status_code == 200, r.text
got = r.json()
assert got["main"]["name"] == "Casa mia" and got["main"]["cards"] == 0 and [n["id"] for n in got["networks"]] == ["neta"], got
after = snapshot()
for table in TABLES:
    assert after[table] == [row for row in before[table] if not of_main(row)], (table, after[table])
assert history.meta_get(newdevices.BASELINE_KEY) is None and history.meta_get("some_other_value") == "kept"
assert devices_config.load_devices() == kept["cards"]
assert sorted(passive_store.snapshot()["adopted"]) == sorted(kept["adopted"])
assert network_store.rows() == kept["networks"] and network_store.main_name() == "Casa mia"
assert blocklist.list_items() == kept["ignored"], blocklist.list_items()

# 3) as at the first install: the next cycle is the starting point, no alert; only what comes after it is new
seen = {mac("M", i).upper(): {"ip": ip("M", i), "hostname": None, "vendor": None} for i in (4, 5, 20)}
assert newdevices.evaluate(seen, set(), set(), now=1000.0) == ([], []), "no flood of new devices after the purge"
assert history.meta_get(newdevices.BASELINE_KEY) is not None
fresh, listed = newdevices.evaluate({**seen, mac("M", 21).upper(): {"ip": ip("M", 21), "hostname": None, "vendor": None}}, set(), set(), now=1060.0)
assert [d["mac"] for d in fresh] == [mac("M", 21).upper()] and [d["mac"] for d in listed] == [mac("M", 21).upper()], (fresh, listed)

# 4) an unknown network is still a 404
assert c.get("/api/networks/nope/purge").status_code == 404 and c.post("/api/networks/nope/purge").status_code == 404
print("check_network_purge_main: ok")
