# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The person's inventory (export/inventory.py): the columns, sorted by IP as numbers, the hidden addresses (same placeholders in the whole
file, names kept), and a CSV that a spreadsheet never runs as a formula (a cell starting with = + - @ tab or CR gets an apostrophe);
the route gives CSV or JSON as a download and refuses another format.
    python tests/check_inventory_export.py"""
import csv
import io
import json
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import inventory as inv  # noqa: E402

cards = [
    {"id": "b", "name": "=HYPERLINK(\"http://x\",\"click\")", "type": "printer", "brand": "HP", "ip": "192.168.1.10", "mac": "B8:27:EB:DD:EE:01", "online": False, "last_seen": 1000},
    {"id": "a", "name": "NAS", "type": "server", "brand": "Synology", "ip": "192.168.1.9", "mac": "B8:27:EB:DD:EE:02", "online": True, "area": "Studio"},
    {"id": "c", "name": "-phone", "type": "phone", "brand": "", "ip": "", "mac": "", "online": False},
]
rows = inv.rows(cards, {"a": 500}, 2000)
assert [r["name"] for r in rows] == ["NAS", "=HYPERLINK(\"http://x\",\"click\")", "-phone"], rows                 # 1.9 before 1.10, no address last
assert rows[0]["last_seen"] == "1970-01-01T00:33:20+00:00" and rows[0]["first_seen"] == "1970-01-01T00:08:20+00:00" and rows[0]["area"] == "Studio"

# CSV: header, formula guard on every cell
text = inv.to_csv(rows)
table = list(csv.reader(io.StringIO(text)))
assert table[0] == list(inv.COLUMNS)
assert table[2][0].startswith("'=HYPERLINK") and table[3][0] == "'-phone" and table[1][0] == "NAS"
assert table[1][5] == "yes" and table[2][5] == "no"
for bad in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
    assert inv.safe_cell(bad) == "'" + bad
assert inv.safe_cell("Living room") == "Living room" and inv.safe_cell(None) == ""

# hidden: the same placeholder for the same address, names kept
h = inv.hidden(rows)
assert h[0]["ip"].startswith("10.") and h[0]["ip"] != "192.168.1.9" and h[0]["mac"][:8] == "B8:27:EB" and h[0]["mac"] != "B8:27:EB:DD:EE:02"
assert h[0]["name"] == "NAS" and h[1]["ip"] != h[0]["ip"]
assert "192.168.1." not in inv.to_csv(h) and "DD:EE:0" not in inv.to_json(h)
assert json.loads(inv.to_json(rows))["columns"] == list(inv.COLUMNS)

from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402
state.devices["nas"] = {"id": "nas", "ip": "192.168.1.9", "mac": "B8:27:EB:DD:EE:02", "online": True, "name": "NAS"}
client = TestClient(main.app)
r = client.get("/api/ha/inventory?format=csv")
assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"] and "192.168.1.9" in r.text
r = client.get("/api/ha/inventory?format=json&hide=1")
assert r.status_code == 200 and "192.168.1.9" not in r.text and json.loads(r.text)["devices"][0]["name"] == "NAS"
assert client.get("/api/ha/inventory?format=xml").status_code == 400
print("check_inventory_export: ok")
