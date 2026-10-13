"""Reference test of the brand routes: rules written by hand (kinds, limits, replacement of the same kind+text, deletion), the preview of the brand a
name or MAC would get, the database update (success, refused while another runs, each failure code), and the automatic-update switch."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import i18n  # noqa: E402
from app.recognition import brands, oui_update  # noqa: E402
from app.routes import brands as routes_brands  # noqa: E402

i18n.use("en")
tmp = Path(tempfile.mkdtemp())
brands._USER_PATH = tmp / "brands.json"
brands._cache.update(stamp=None, rules=None)
app = FastAPI()
app.include_router(routes_brands.router)
c = TestClient(app)

state = c.get("/api/brands").json()
assert state["rules"] == [] and set(state["oui"]) == {"blocks", "source", "updated", "age_days"} and isinstance(state["auto_update"], bool)

kind = sorted(brands.KINDS)[0]
assert c.post("/api/brands/rules", content="nonsense").status_code == 400
assert c.post("/api/brands/rules", json=[1]).status_code == 400
assert c.post("/api/brands/rules", json={"kind": "bogus", "text": "abc", "brand": "X"}).status_code == 400
assert c.post("/api/brands/rules", json={"kind": kind, "text": "a", "brand": "X"}).status_code == 400, "text too short"
assert c.post("/api/brands/rules", json={"kind": kind, "text": "abc", "brand": ""}).status_code == 400, "brand empty"
r = c.post("/api/brands/rules", json={"kind": kind, "text": " Acme-Lamp ", "brand": " Acme "})
rules = r.json()["rules"]
assert r.status_code == 200 and len(rules) == 1 and rules[0]["text"] == "Acme-Lamp" and rules[0]["brand"] == "Acme"
rules = c.post("/api/brands/rules", json={"kind": kind, "text": "acme-lamp", "brand": "Acme Lighting"}).json()["rules"]
assert len(rules) == 1 and rules[0]["brand"] == "Acme Lighting", "same kind+text replaces the brand"
rid = rules[0]["id"]
assert c.delete("/api/brands/rules/nope").status_code == 404
assert c.delete(f"/api/brands/rules/{rid}").json()["rules"] == []

assert "brand" in c.post("/api/brands/preview", json={"mac": "b8:27:eb:11:22:33", "name": ""}).json()
assert c.post("/api/brands/preview", content="garbage").json() == c.post("/api/brands/preview", json={}).json()

# the database update: success, one at a time, and every failure code has its own answer
oui_update.update = lambda: {"blocks": 123, "updated": 1700000000}
assert c.post("/api/brands/update").json() == {"ok": True, "blocks": 123, "updated": 1700000000}
for code in ("network", "invalid", "too_small", "write"):
    def failing(code=code):
        raise oui_update.OuiUpdateError(code, "boom")
    oui_update.update = failing
    assert c.post("/api/brands/update").status_code == 502, code


def unexpected():
    raise RuntimeError("disk")


oui_update.update = unexpected
assert c.post("/api/brands/update").status_code == 502
class _Busy:                                    # an update is running: a stub, so a regression fails instead of waiting for a lock forever
    def locked(self):
        return True


real_lock, routes_brands._update_lock = routes_brands._update_lock, _Busy()
assert c.post("/api/brands/update").status_code == 409, "an update is already running"
routes_brands._update_lock = real_lock

assert c.post("/api/brands/auto-update", json={"enabled": "yes"}).status_code == 400
assert c.post("/api/brands/auto-update", json={"enabled": False}).json()["auto_update"] is False
print("TUTTO OK")
