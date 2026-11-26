"""The order of the groups on the page (1.0.4, setting "group_order"): [] = the default order; POST /api/settings saves a list of known
groups, each once, made whole (the missing ones follow in the default order); an unknown group, a repeat or a value that is not a list is
refused (400, nothing saved). A file written by hand with an unknown group is read without it. Temporary data folder, nothing contacted.
    python tests/check_settings_group_order.py"""
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import device_groups  # noqa: E402
from app.routes import settings_routes  # noqa: E402
from app.storage import settings  # noqa: E402

app = FastAPI()
app.include_router(settings_routes.router)
client = TestClient(app, raise_server_exceptions=False)
failures = []
DEFAULT = list(device_groups.TYPE_ORDER)


def check(cond, msg):
    print(("ok: " if cond else "FAILED: ") + msg)
    if not cond:
        failures.append(msg)


check(settings.DEFAULTS.get("group_order") == [], "the default is [] (the default order)")
check(client.get("/api/settings").json().get("group_order") == [], "GET /api/settings says it")
r = client.post("/api/settings", json={"group_order": ["camera", "router"]})
whole = ["camera", "router"] + [g for g in DEFAULT if g not in ("camera", "router")]
check(r.status_code == 200 and r.json().get("group_order") == whole, "a partial order is saved whole: %s %s" % (r.status_code, r.text[:200]))
check(settings.load()["group_order"] == whole and len(whole) == 10, "and read back")
for wrong in (["router", "router"], ["toaster"], "router", [1], None, {"router": 1}):
    r = client.post("/api/settings", json={"group_order": wrong})
    check(r.status_code == 400, "refused: %r -> %s" % (wrong, r.status_code))
check(settings.load()["group_order"] == whole, "and nothing was saved")
r = client.post("/api/settings", json={"group_order": []})
check(r.status_code == 200 and settings.load()["group_order"] == [], "[] goes back to the default order")
check(settings.load()["phone_hold_ha"] is True and settings.load()["poll_interval"] == 30, "the other settings are untouched")

# a file written by hand, or by the debug build with 16 groups (climate, water...): the unknown names are left out silently, the missing
# ones appended
settings.SETTINGS_PATH.write_text(json.dumps({"group_order": ["climate", "camera", "toaster", "camera", "water", "pc"]}), encoding="utf-8")
read = settings.load()["group_order"]
check(read[:2] == ["camera", "pc"] and sorted(read) == sorted(DEFAULT) and len(read) == 10, "a saved order is read clean: %s" % read)
settings.SETTINGS_PATH.write_text(json.dumps({"group_order": "nonsense"}), encoding="utf-8")
check(settings.load()["group_order"] == [], "a value that is not a list is the default")
print("ALL OK" if not failures else "%d FAILED" % len(failures))
sys.exit(1 if failures else 0)
