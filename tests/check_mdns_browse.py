"""Characterisation test of the Bonjour browsing inside scan/mdns_listener._listen: the handlers that zeroconf calls (a new service type, a service instance) are taken from the browsers the listener creates
and called by hand with a fake zeroconf. What the listener does is stored in tests/golden/mdns_browse.json, written from the code as it was before the browsing was moved out of the nested functions:
the first browser asks for the service types; a type is browsed once; a removed type or instance does nothing; an instance is read with a request of 3000 ms and recorded once for every IPv4 address, nothing if the
request fails, answers no or raises; when the listener is cancelled the browsers and the reading tasks are cancelled, zeroconf is closed even if a browser fails to cancel, and the memory is saved last.
Regenerate only on purpose:  MDNS_BROWSE_GOLDEN_UPDATE=1 python tests/check_mdns_browse.py"""
import asyncio
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
GOLDEN = Path(__file__).parent / "golden" / "mdns_browse.json"
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
from app.scan import mdns_listener as ml  # noqa: E402

ml.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
ml.record = lambda *a: LOG.append(["record", list(a)])
ml._housekeeping = lambda: LOG.append(["housekeeping"])
ml._save = lambda: LOG.append(["save"])


async def run():
    task = asyncio.ensure_future(ml._listen())
    await asyncio.sleep(0.05)
    meta = BROWSERS[0]
    on_type = meta.handlers[0]
    on_type(None, None, "_http._tcp.local.", "added")
    on_type(None, None, "_http._tcp.local.", "added")              # already browsed
    on_type(None, None, "_gone._tcp.local.", "removed")            # removed: nothing
    on_type(None, None, "_bad._tcp.local.", "added")
    on_instance = BROWSERS[1].handlers[0]
    for name, state in (("ok.one._http._tcp.local.", "added"), ("ok.two._http._tcp.local.", "added"), ("no.answer._http._tcp.local.", "added"),
                        ("raises._http._tcp.local.", "added"), ("no.address._http._tcp.local.", "added"), ("gone._http._tcp.local.", "removed")):
        on_instance(None, "_http._tcp.local.", name, state)
    await asyncio.sleep(0.1)
    LOG.append(["browsers", len(BROWSERS)])
    ml._dirty = True                                              # something is waiting to be saved when the listener ends
    task.cancel()
    try:
        await asyncio.wait_for(task, 2)
        LOG.append(["swallowed the cancel"])
    except asyncio.CancelledError:
        LOG.append(["cancelled"])


asyncio.run(run())
got = json.loads(json.dumps(LOG, default=str))
if os.environ.get("MDNS_BROWSE_GOLDEN_UPDATE"):
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    print("golden written:", len(got), "entries")
    sys.exit(0)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert [x for x in got if x[0] != "record"] == [x for x in want if x[0] != "record"], "the browsing is not what it was\n" + json.dumps(got, indent=1)[:2500]
assert sorted(map(json.dumps, [x for x in got if x[0] == "record"])) == sorted(map(json.dumps, [x for x in want if x[0] == "record"])), "the records are not what they were"
assert ["save"] in got and got.index(["save"]) > got.index(["zeroconf closed"]), "the memory is saved last, after the browsing is closed"
assert got[-1] == ["cancelled"] and ["zeroconf closed"] in got and sum(1 for x in got if x[0] == "record") == 3
print("TUTTO OK")
