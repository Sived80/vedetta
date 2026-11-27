# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Names the person or the house wrote that live only in the stores added with 1.0 must be masked in the export for the developer too:
the names of the networks (and of the main one), the former names of a card (identity_change), the names that devices behind the router
gave (routed_seen.host) and the names Home Assistant gives the devices it sees and Vedetta does not scan (passive_devices.json)."""
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_zip  # noqa: E402
from app.networks import model  # noqa: E402
from app.storage import network_store, passive_store  # noqa: E402
from app.storage.history import history  # noqa: E402
import ipaddress  # noqa: E402

MAIN = model.Network("main", ipaddress.ip_network("192.168.1.0/24"), frozenset({"direct"}), "full", "confirmed")
network_store.add({"id": "neta", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "presence", "state": "confirmed", "name": "Camera di Anna"}, MAIN)
network_store.set_main_name("Casa Rossi")
now = time.time()
history.identity_record([{"device_id": "d1", "ts": now, "field": "name", "old": "iPhone di Marco Rossi", "new": "Telefono", "source": "user"}])
history.routed_write([{"network": "192.168.60.0/24", "ip": "192.168.60.7", "first_seen": now, "last_seen": now, "mac": "AA:BB:CC:00:00:07",
                       "host": "Tablet-Giulia", "status": "on"}])
passive_store.record_read([{"mac": "aa:bb:cc:00:00:08", "ip": "192.168.60.8", "name": "Lavatrice Bianchi", "host": "lavatrice-bianchi"}], now)

anon = export_zip._collect([])
text = "networks: Camera di Anna, Casa Rossi; was iPhone di Marco Rossi; routed Tablet-Giulia; ha Lavatrice Bianchi lavatrice-bianchi"
masked = anon.text(text)
for secret in ("Anna", "Rossi", "Giulia", "Bianchi"):
    assert secret.lower() not in masked.lower(), (secret, masked)
assert anon.leaks(masked) == [], anon.leaks(masked)
print("ALL OK")
