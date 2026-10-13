"""Characterisation test of the Bonjour browsing of the SEARCH (scan/scan_mdns._mdns_browse, which fills the list `found`), with a fake zeroconf whose handlers are called by hand. Stored in
tests/golden/mdns_scan_browse.json, written from the code as it was before the browsing shared by the search and by the continuous listener was moved into one module: the first browser asks for the
service types; a type is browsed once, never after the window of the types has closed, never when removed; an instance is read with the request timeout of the search and added to `found` as
(type without .local., instance, address, txt) once for every IPv4 address; nothing when the request fails, answers no or raises; at the end the browsers are cancelled and zeroconf is closed, also when
the search is cancelled from outside, even if a browser fails to cancel.
Regenerate only on purpose:  MDNS_SCAN_BROWSE_GOLDEN_UPDATE=1 python tests/check_mdns_scan_browse.py"""
import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
GOLDEN = Path(__file__).parent / "golden" / "mdns_scan_browse.json"
LOG: list = []
BEHAVIOUR = {"ok.one": ("yes", ["10.0.0.5"]), "ok.two": ("yes", ["10.0.0.6", "10.0.0.7"]), "no.answer": ("no", ["10.0.0.8"]),
             "raises": ("raise", ["10.0.0.9"]), "no.address": ("yes", [])}
BROWSERS: list = []


class FakeInfo:
    def __init__(self, stype, name):
        self.key = name.split("._")[0] if "._" in name else name
        self.properties = {b"model": b"M1"}
        LOG.append(["info", stype, name])

    async def async_request(self, zc, timeout):
        LOG.append(["request", self.key, timeout])
        answer = BEHAVIOUR[self.key][0]
        if answer == "raise":
            raise OSError("network down")
        return answer == "yes"

    def parsed_addresses(self, version):
        return list(BEHAVIOUR[self.key][1])


class FakeBrowser:
    def __init__(self, zc, name, handlers=None):
        self.name, self.handlers = name, handlers
        BROWSERS.append(self)
        LOG.append(["browser", name])

    async def async_cancel(self):
        LOG.append(["browser cancelled", self.name])
        if self.name == "_bad._tcp.local.":
            raise RuntimeError("cannot cancel")


class FakeZeroconf:
    def __init__(self, ip_version=None):
        self.zeroconf = object()
        LOG.append(["zeroconf", ip_version])

    async def async_close(self):
        LOG.append(["zeroconf closed"])


zc = types.ModuleType("zeroconf")
zc.IPVersion = types.SimpleNamespace(V4Only="v4")
zc.ServiceStateChange = types.SimpleNamespace(Added="added", Removed="removed")
zca = types.ModuleType("zeroconf.asyncio")
zca.AsyncServiceBrowser, zca.AsyncServiceInfo, zca.AsyncZeroconf = FakeBrowser, FakeInfo, FakeZeroconf
sys.modules["zeroconf"], sys.modules["zeroconf.asyncio"] = zc, zca
from app.scan import scan_mdns  # noqa: E402

scan_mdns._MDNS_BUDGET = 1.2            # the browse sleeps for budget - 0.5 s, then waits up to 0.4 s for the readings
scan_mdns._MDNS_TYPES_WINDOW = 0.3      # no new type after 0.3 s


async def feed(found):
    await asyncio.sleep(0.05)
    on_type = BROWSERS[0].handlers[0]
    on_type(None, None, "_http._tcp.local.", "added")
    on_type(None, None, "_http._tcp.local.", "added")              # already browsed
    on_type(None, None, "_gone._tcp.local.", "removed")            # removed: nothing
    on_type(None, None, "_bad._tcp.local.", "added")
    on_instance = BROWSERS[1].handlers[0]
    for name, state in (("ok.one._http._tcp.local.", "added"), ("ok.two._http._tcp.local.", "added"), ("no.answer._http._tcp.local.", "added"),
                        ("raises._http._tcp.local.", "added"), ("no.address._http._tcp.local.", "added"), ("gone._http._tcp.local.", "removed")):
        on_instance(None, "_http._tcp.local.", name, state)
    await asyncio.sleep(0.4)                                        # the window of the types is closed
    on_type(None, None, "_late._tcp.local.", "added")


async def completed():
    found: list = []
    feeder = asyncio.ensure_future(feed(found))
    await scan_mdns._mdns_browse(found)
    await feeder
    LOG.append(["found", sorted(found)])
    LOG.append(["browsers", len(BROWSERS)])


async def cancelled():
    found: list = []
    task = asyncio.ensure_future(scan_mdns._mdns_browse(found))
    await asyncio.sleep(0.2)
    task.cancel()
    try:
        await asyncio.wait_for(task, 2)
        LOG.append(["swallowed the cancel"])
    except asyncio.CancelledError:
        LOG.append(["cancelled"])


got = {}
for name, case in (("completed", completed), ("cancelled", cancelled)):
    LOG.clear()
    BROWSERS.clear()
    asyncio.run(case())
    got[name] = json.loads(json.dumps(LOG, default=str))
if os.environ.get("MDNS_SCAN_BROWSE_GOLDEN_UPDATE"):
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    print("golden written:", {k: len(v) for k, v in got.items()})
    sys.exit(0)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))


def stable(entries):                    # the readings run at the same time: their order is not part of the behaviour
    return sorted(json.dumps(x) for x in entries)


for name in got:
    assert stable(got[name]) == stable(want[name]), name + ": the browsing is not what it was\n" + json.dumps(got[name], indent=1)[:2500]
found = [x for x in got["completed"] if x[0] == "found"][0][1]
assert len(found) == 3 and found[0][0] == "_http._tcp" and ["browser", "_late._tcp.local."] not in got["completed"]
assert got["cancelled"][-1] == ["cancelled"] and ["zeroconf closed"] in got["cancelled"]
print("TUTTO OK")
