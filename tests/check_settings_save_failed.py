"""A settings file that cannot be written (disk full, read-only folder) gives the same clean 500 «Salvataggio non riuscito» on every route that
saves settings: /api/settings, /api/sentinel, /api/snmp (the last two used to let the OSError through, a bare 500 with a traceback).
Found by the review of 1.0.1. Temporary data folder, nothing contacted.
    python tests/check_settings_save_failed.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.routes import settings_routes  # noqa: E402
from app.storage import settings  # noqa: E402


def full_disk(data):
    raise OSError(28, "No space left on device")


settings._save = full_disk
app = FastAPI()
app.include_router(settings_routes.router)
client = TestClient(app, raise_server_exceptions=False)
failures = []
for path, body in (("/api/settings", {}), ("/api/sentinel", {"ha_events": True}), ("/api/snmp", {"snmp_router": "10.0.0.1"})):
    r = client.post(path, json=body)
    if r.status_code != 500 or r.headers.get("content-type", "").split(";")[0] != "application/json" or r.json().get("detail") != "Salvataggio non riuscito":
        failures.append((path, r.status_code, r.text[:60]))
assert not failures, failures
print("check_settings_save_failed: ok")
