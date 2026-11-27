# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""POST /api/brands/update downloads the IEEE list of MAC prefixes: with the app option internet_mac_database off it sends nothing and says
why (19/11 review: the option promises that nothing goes out; no page calls this route, but it must keep the promise too)."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
os.environ["VEDETTA_INTERNET_MAC_DB"] = "false"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import brands  # noqa: E402

CALLS = []
brands.oui_update.update = lambda: CALLS.append(1) or {"blocks": 1, "updated": 1}
c = TestClient(FastAPI())
c.app.include_router(brands.router)
r = c.post("/api/brands/update")
assert r.status_code == 403 and CALLS == [] and r.json()["detail"], (r.status_code, r.text, CALLS)
os.environ["VEDETTA_INTERNET_MAC_DB"] = "true"
r = c.post("/api/brands/update")
assert r.status_code == 200 and CALLS == [1], (r.status_code, r.text)
print("ALL OK")
