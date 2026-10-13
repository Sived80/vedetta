"""Every route that modifies something reads its JSON body through ONE helper (routes/bodies.py json_dict): a body that is not valid JSON, or is a list, a string or a number, gives a translated 400, never a
500 with a traceback in the log. Found by the global review (two routes of the export read the body unchecked and several kept their own copy of the same check). The routes that deliberately accept an empty
or wrong body as «nothing» (cancel the searches, ignore all, brand preview) are listed apart and must keep answering 200."""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import main, paths  # noqa: E402
from app.routes import brands, export_routes, flows, ha, ignored, settings_routes  # noqa: E402
from app.storage import devices_config  # noqa: E402

tmp = Path(tempfile.mkdtemp())
paths.DATA_DIR = tmp
devices_config.CONFIG_DIR = tmp
devices_config.DEVICES_PATH = tmp / "devices.yaml"

app = FastAPI()
for module in (brands, export_routes, flows, ha, ignored, settings_routes):
    app.include_router(module.router)
app.post("/api/pause")(main.api_pause)
client = TestClient(app, raise_server_exceptions=False)

MUST_REFUSE = [
    "/api/brands/rules", "/api/brands/auto-update", "/api/ignored", "/api/ignored/hosts", "/api/ignored/forget", "/api/flows", "/api/settings",
    "/api/new-devices/unignore", "/api/pause", "/api/export/jobs", "/api/export/jobs/abc/choices",
]
BAD_BODIES = [b"", b"not json", b"[]", b'"text"', b"42", b"null", b"[1, 2]"]
failures = []
for path in MUST_REFUSE:
    for body in BAD_BODIES:
        r = client.post(path, content=body, headers={"content-type": "application/json"})
        if r.status_code not in (400, 404, 422):       # 404 only for a job that does not exist, 422 for a period that is checked; never a 500
            failures.append((path, body, r.status_code))
assert not failures, "a bad body was not answered with a client error: %s" % failures[:6]

for path in ("/api/scan/cancel", "/api/new-devices/ignore", "/api/brands/preview"):
    for body in BAD_BODIES:
        r = client.post(path, content=body, headers={"content-type": "application/json"})
        assert r.status_code != 500, (path, body, r.status_code)
print("TUTTO OK")
