# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 «Approdo» (27/11, the person: «in Vedetta come so che HA è connessa?»): in Docker the page and the log say whether Home Assistant
is connected, and how to connect it.
- ha_registry.link(): connected (devices, time), or the problem: no_url (no VEDETTA_HA_URL), no_token (no token), refused (Home
  Assistant refused the token), unreachable (anything else); help_hidden = the person ticked «Do not show again»;
- the log says it in English once per change of state (connected with the number of devices, refused, unreachable);
- /api/ha/summary carries ha_link in Docker only (under the Supervisor Home Assistant is always there);
- the setting ha_help_hidden is a boolean of /api/settings.
Invented addresses only.
    python tools/run_test.py check_docker_ha_link.py"""
import asyncio
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
os.environ["VEDETTA_MODE"] = "docker"
for k in ("SUPERVISOR_TOKEN", "VEDETTA_HA_URL", "VEDETTA_HA_TOKEN", "VEDETTA_HA_TOKEN_FILE", "VEDETTA_HA_WS"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from pathlib import Path  # noqa: E402
from app import runtime  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.storage import settings  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


runtime.SECRETS_DIR = Path(tempfile.mkdtemp())
said = []
ha_registry.logger.warning = lambda msg, *a: said.append(msg % a if a else msg)
ha_registry.logger.info = lambda msg, *a: said.append(msg % a if a else msg)

link = ha_registry.link()
check(link["connected"] is False and link["problem"] == "no_url" and link["help_hidden"] is False, "no address: not configured, no_url: %s" % link)
os.environ["VEDETTA_HA_URL"] = "http://192.0.2.10:8123"
check(ha_registry.link()["problem"] == "no_token", "an address without a token: no_token")
(runtime.SECRETS_DIR / "ha_token").write_text("a-token-for-tests", encoding="utf-8")


async def fetch_refused():
    raise RuntimeError("autenticazione rifiutata: auth_invalid")


async def fetch_down():
    raise OSError("connection refused")


async def fetch_ok():
    return {"devices": [{"id": "d1", "name": "Node", "connections": [["mac", "02:00:00:00:00:91"]], "config_entries": []}],
            "entities": [], "areas": [], "entries": []}

ha_registry._fetch = fetch_refused
asyncio.run(ha_registry.refresh())
check(ha_registry.link()["problem"] == "refused", "Home Assistant refused the token: refused")
check(any("Home Assistant refused the token" in s for s in said), "the log says it in English: %s" % said[-1:])
n = len(said)
asyncio.run(ha_registry.refresh())
check(not any("refused the token" in s for s in said[n:]), "and only once while it stays so")
ha_registry._fetch = fetch_down
asyncio.run(ha_registry.refresh())
check(ha_registry.link()["problem"] == "unreachable" and any("cannot be reached" in s for s in said), "Home Assistant down: unreachable, said in English")
ha_registry._fetch = fetch_ok
asyncio.run(ha_registry.refresh())
link = ha_registry.link()
check(link["connected"] is True and link["problem"] is None and link["devices"] == 1 and link["at"], "connected, with the number of devices: %s" % link)
check(any(s.startswith("Home Assistant connected: 1 device") for s in said), "the log says connected in English")
check(all("a-token-for-tests" not in s for s in said), "the token is never in the log")

settings.update({"ha_help_hidden": True})
check(ha_registry.link()["help_hidden"] is True, "«Do not show again» is kept on the server")
try:
    settings.update({"ha_help_hidden": "yes"})
    check(False, "a setting of the wrong type is refused")
except ValueError:
    check(True, "a setting of the wrong type is refused")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.auth import passwords, store  # noqa: E402
store.set_password_hash(passwords.hash_password("correct horse battery staple"))
web = TestClient(app, base_url="http://192.0.2.200:8765", follow_redirects=False)
web.post("/login", data={"password": "correct horse battery staple"}, headers={"Sec-Fetch-Site": "same-origin"})
check(web.get("/api/ha/summary").json().get("ha_link", {}).get("connected") is True, "the summary carries ha_link in Docker")
os.environ["VEDETTA_MODE"] = "addon"
check(web.get("/api/ha/summary").json().get("ha_link") is None, "and not under the Supervisor")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
