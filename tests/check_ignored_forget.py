"""Forget an ignored device: it leaves the list and what the app remembers about it goes too (the known MAC, the DHCP name, the Bonjour card);
a normal known device is never touched, and a wrong request is refused."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import ignored as routes_ignored  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.storage import blocklist, journal  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
blocklist.PATH = tmp / "ignored.json"
blocklist._cache.update(stamp=None, items=[])
journal.PATH = tmp / "journal.jsonl"       # the notes of this test must not reach the real journal
dhcp.STORE_PATH = tmp / "dhcp_seen.json"
mdns_listener.STORE_PATH = tmp / "mdns.json"
H = History(tmp / "vedetta.db")
routes_ignored.history = H
dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()

now = time.time()
H.known_set("AA:BB:CC:00:00:01", now, "192.168.1.21", "Acme", "tv-salotto", "ignored")     # found on the network, ignored
H.known_set("AA:BB:CC:00:00:02", now, "192.168.1.22", "Acme", "phone", "new")               # not ignored: never touched
dhcp.seen["aa:bb:cc:00:00:01"] = {"hostname": "tv-salotto", "seen": now}
dhcp.seen["aa:bb:cc:00:00:02"] = {"hostname": "phone", "seen": now}
mdns_listener.by_mac["aa:bb:cc:00:00:01"] = {"name": "TV", "ip": "192.168.1.21"}
mdns_listener.by_ip["192.168.1.21"] = {"name": "TV"}
mdns_listener.by_mac["aa:bb:cc:00:00:02"] = {"name": "Phone", "ip": "192.168.1.22"}

app = FastAPI()
app.include_router(routes_ignored.router)
c = TestClient(app)

# a device found on the network
r = c.post("/api/ignored/forget", json={"mac": "aa-bb-cc-00-00-01"})
assert r.status_code == 200, r.text
assert r.json()["macs"] == [], "esce dalla lista degli ignorati"
assert "AA:BB:CC:00:00:01" not in H.known_all(), "il MAC non e' piu' ricordato"
assert "aa:bb:cc:00:00:01" not in dhcp.seen and "aa:bb:cc:00:00:01" not in mdns_listener.by_mac and "192.168.1.21" not in mdns_listener.by_ip, "nome DHCP e scheda Bonjour dimenticati"
assert "AA:BB:CC:00:00:02" in H.known_all() and "aa:bb:cc:00:00:02" in dhcp.seen and "aa:bb:cc:00:00:02" in mdns_listener.by_mac, "gli altri non si toccano"

# a normal known device (status new) cannot be wiped through this door: its row stays
r = c.post("/api/ignored/forget", json={"mac": "AA:BB:CC:00:00:02"})
assert r.status_code == 200 and "AA:BB:CC:00:00:02" in H.known_all(), "un dispositivo non ignorato resta noto"

# a device ignored from a search (by MAC and by IP)
items = c.post("/api/ignored", json={"kind": "mac", "value": "AA:BB:CC:00:00:03", "label": "Stampante"}).json()["items"]
mdns_listener.by_mac["aa:bb:cc:00:00:03"] = {"name": "Printer", "ip": "192.168.1.23"}
r = c.post("/api/ignored/forget", json={"id": items[0]["id"]})
assert r.status_code == 200 and r.json()["items"] == [], "esce dalla lista"
assert "aa:bb:cc:00:00:03" not in mdns_listener.by_mac, "anche la memoria del MAC"
items = c.post("/api/ignored", json={"kind": "ip", "value": "192.168.1.24"}).json()["items"]
mdns_listener.by_ip["192.168.1.24"] = {"name": "Cam"}
assert c.post("/api/ignored/forget", json={"id": items[0]["id"]}).status_code == 200 and "192.168.1.24" not in mdns_listener.by_ip

# wrong requests
assert c.post("/api/ignored/forget", json={"id": "nope"}).status_code == 404
assert c.post("/api/ignored/forget", json={"mac": "zz"}).status_code == 400
assert c.post("/api/ignored/forget", json={}).status_code == 400
journal._entries.clear()
print("TUTTO OK")
