# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""GET /api/ignored gives each entry ignored by MAC its last known address ("ip"), so the panel «Networks» can show it under its network:
the most recent address the MAC layer saw it at (ip_mac), otherwise the one of the new devices (known_macs), otherwise None (the entry then
belongs to «In every network»). Entries by address or by name are as before. Invented private addresses only.
    python tests/check_ignored_last_ip.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import ignored  # noqa: E402
from app.storage import blocklist  # noqa: E402
from app.storage.history import history  # noqa: E402

db = history._db      # ip_mac is written as the MAC layer writes it (normalize_mac: upper case, colons)
db.execute("INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen) VALUES ('192.168.60.5', '02:00:5E:60:00:07', 'arp', 1, 2)")
db.execute("INSERT INTO ip_mac (ip, mac, source, first_seen, last_seen) VALUES ('192.168.60.7', '02:00:5E:60:00:07', 'arp', 3, 9)")
db.execute("INSERT INTO known_macs (mac, first_seen, ip, status) VALUES ('02:00:5E:50:00:08', 1, '192.168.50.8', 'ignored')")
db.commit()
for kind, value in (("mac", "02:00:5E:60:00:07"), ("mac", "02:00:5e:50:00:08"), ("mac", "02:00:5E:99:00:01"), ("ip", "192.168.70.4"), ("name", "phone of a guest")):
    blocklist.add(kind, value)

c = TestClient(FastAPI())
c.app.include_router(ignored.router)
items = c.get("/api/ignored").json()["items"]
got = {i["value"]: i.get("ip", "absent") for i in items}
assert got == {"02:00:5E:60:00:07": "192.168.60.7", "02:00:5e:50:00:08": "192.168.50.8", "02:00:5E:99:00:01": None,
               "192.168.70.4": "absent", "phone of a guest": "absent"}, got
assert [{k: v for k, v in i.items() if k != "ip"} for i in items] == blocklist.list_items(), "nothing else changes"
print("check_ignored_last_ip: ok")
