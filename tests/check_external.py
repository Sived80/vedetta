"""The functions that reach the internet can be switched off by the add-on options (app/external.py, scan/internet.py, recognition/oui_update.py):
the variables are read as the add-on writes them (run.sh), a function that is off sends nothing (no DNS query, no traceroute), the target of the
traceroute is checked before it becomes an argument of nmap, the MAC database follows the option when there is one and its own setting file when
there is not, and the page learns the state of all three through the summary (routes/ha._external_info)."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
from app import external  # noqa: E402
from app.recognition import brands, oui_update  # noqa: E402
from app.scan import internet, scanner  # noqa: E402

NAMES = ("VEDETTA_INTERNET_PUBLIC_IP", "VEDETTA_INTERNET_PATH", "VEDETTA_INTERNET_MAC_DB", "VEDETTA_INTERNET_PATH_TARGET")


def env(**kw):
    for n in NAMES:
        os.environ.pop(n, None)
    for k, v in kw.items():
        os.environ["VEDETTA_INTERNET_" + k.upper()] = v


# --- the variables, as the add-on writes them (bashio prints true / false; a missing option prints null)
env()
assert external.public_ip_enabled() and external.path_enabled() and external.mac_database_setting() is None, "no variable: as it always was (the MAC database has its own file)"
env(public_ip="false", path="true", mac_db="false")
assert not external.public_ip_enabled() and external.path_enabled() and external.mac_database_setting() is False
env(public_ip="true", path="false", mac_db="true")
assert external.public_ip_enabled() and not external.path_enabled() and external.mac_database_setting() is True
env(public_ip="null", path="", mac_db="null")
assert external.public_ip_enabled() and external.path_enabled(), "an option missing after an update is on, as the rest"
assert external.any_internet_check() is True
env(public_ip="false", path="false")
assert external.any_internet_check() is False

# --- the target of the traceroute becomes an argument of nmap: only a name or an address gets through
for good in ("example.org", "9.9.9.9", "2606:4700::1111", "router-1.lan"):
    env(path_target=good)
    assert external.path_target() == good, good
env()
assert external.path_target() == "1.1.1.1"
for bad in ("-oX /tmp/x", "--script=x", "a b", "x;y", "$(id)", "a" * 300, "http://x/"):
    env(path_target=bad)
    assert external.path_target() == "1.1.1.1", ("not accepted", bad)
env(path_target="  ")
assert external.path_target() == "1.1.1.1"

# --- the check sends only what is on
sent = {"dns": 0, "nmap": []}


async def fake_ip(timeout=3.0):
    sent["dns"] += 1
    return "203.0.113.7"


TRACE = '<nmaprun><host><trace><hop ttl="1" ipaddr="192.0.2.1"/><hop ttl="2" ipaddr="198.51.100.1"/></trace></host></nmaprun>'


async def fake_nmap(args, semaphore=None):
    sent["nmap"].append(args)
    return TRACE


internet.public_ip = fake_ip
scanner._run_nmap = fake_nmap


def run():
    sent["dns"], sent["nmap"] = 0, []
    return asyncio.run(internet.check())


env()
r = run()
assert sent["dns"] == 1 and len(sent["nmap"]) == 1 and sent["nmap"][0][-1] == "1.1.1.1", "all on: both go out, the traceroute to the default"
assert r["public_ip"] == "203.0.113.7" and r["hops"] == ["192.0.2.1", "198.51.100.1"] and r["checks"] == {"public_ip": True, "path": True}
env(public_ip="false")
r = run()
assert sent["dns"] == 0 and len(sent["nmap"]) == 1 and r["public_ip"] is None and r["hops"] and r["checks"] == {"public_ip": False, "path": True}, "the IP check off: no DNS query"
env(path="false")
r = run()
assert sent["dns"] == 1 and sent["nmap"] == [] and r["hops"] == [] and r["public_ip"] == "203.0.113.7" and r["checks"] == {"public_ip": True, "path": False}, "the path check off: no traceroute"
env(public_ip="false", path="false")
r = run()
assert sent["dns"] == 0 and sent["nmap"] == [] and r["public_ip"] is None and r["hops"] == [], "both off: nothing leaves"
env(public_ip="true", path="true", path_target="9.9.9.9")
run()
assert sent["nmap"][-1][-1] == "9.9.9.9", "the target of the option is the one traced"

# --- the MAC database: the option decides when there is one, the setting file otherwise
brands._USER_PATH = Path(tempfile.mkdtemp()) / "brands.json"
env()
assert oui_update.auto_update_enabled() is False and oui_update.auto_update_locked() is False, "no option: the file decides, off by default (as before)"
brands.update_user({"auto_update": True})
assert oui_update.auto_update_enabled() is True
env(mac_db="false")
assert oui_update.auto_update_enabled() is False and oui_update.auto_update_locked() is True, "the option off wins over the file"
brands.update_user({"auto_update": False})
env(mac_db="true")
assert oui_update.auto_update_enabled() is True and oui_update.auto_update_locked() is True, "the option on wins over the file"

# --- what the page learns (summary)
env(public_ip="false", path="true", mac_db="true", path_target="9.9.9.9")
from app.routes import ha as routes_ha  # noqa: E402
info = routes_ha._external_info()
assert info["public_ip"] == {"on": False} and info["path"] == {"on": True, "target": "9.9.9.9"} and info["mac_database"]["on"] is True and "updated" in info["mac_database"], info
assert set(info) == {"public_ip", "path", "mac_database"}, "only these: nothing else of the configuration (no credential) goes to the page"
print("TUTTO OK")
