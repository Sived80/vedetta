"""The quick search ("Search devices") on a network wider than a /24 asks what the periodic check asks (scan/arpplan.py), never the whole network:
with a mask of 255.0.0.0 `arp-scan --localnet` would ask 16 million addresses, be killed after ARP_TIMEOUT_S and the search would end in an error
(with a /16 too: 65,534 addresses do not fit in that time). A /24 or smaller is asked whole, as always.
1) /24: --localnet, nothing on the standard input; 2) /16 and /8: the own /24, the known devices, at most arpplan.MAX_TARGETS addresses, never --localnet;
3) the plan failing: only the own /24.
Fake commands and a temporary data folder; private placeholder addresses.
    python tests/check_quick_scan_large_network.py"""
import asyncio
import io
import ipaddress
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.scan import arpplan, pipeline, scan_arp  # noqa: E402
from app.storage import devices_config  # noqa: E402

OWN = {"addr": "10.0.0.2/24"}
CALLS: list = []


class FakeProc:
    returncode = 0

    def __init__(self, out: str, call: dict | None = None):
        self.out, self.call = out, call

    async def communicate(self, data=None):
        if self.call is not None:
            self.call["stdin"] = data
        return self.out.encode(), b""


async def fake_exec(*args, **kwargs):
    if args[0] == "arp-scan":
        CALLS.append({"args": args})
        return FakeProc("10.0.0.10\taa:bb:cc:00:00:0a\tMaker A\n", CALLS[-1])
    if "neigh" in args:
        return FakeProc("")
    return FakeProc("3: lan9    inet %s brd 10.255.255.255 scope global lan9\n" % OWN["addr"])


netutil.asyncio.create_subprocess_exec = fake_exec
netutil.lan_iface = lambda: "lan9"
scan_arp.open = lambda *a, **k: io.StringIO("02:00:5e:00:00:02\n")
devices_config.load_devices = lambda: [{"ip": "10.0.3.20"}, {"ip": "10.200.1.5"}, {"name": "no address"}]


def search(addr: str) -> dict:
    OWN["addr"] = addr
    CALLS.clear()
    asyncio.run(pipeline.run_initial())
    assert len(CALLS) == 1, CALLS
    call = CALLS[0]
    targets = call["stdin"].decode().split("\n") if call["stdin"] else []
    return {"localnet": "--localnet" in call["args"], "targets": targets,
            "size": sum(ipaddress.ip_network(t, strict=False).num_addresses for t in targets)}


# 1) a normal network: the whole of it, as always
got = search("10.0.0.2/24")
assert got["localnet"] and got["targets"] == [], got
got = search("10.0.0.2/27")
assert got["localnet"] and got["targets"] == [], got

# 2) wide networks: the plan, never the whole network
for addr in ("10.0.0.2/16", "10.0.0.2/8", "10.0.0.2/22"):
    got = search(addr)
    assert not got["localnet"], (addr, got)
    assert got["targets"][0] == "10.0.0.0/24", (addr, got["targets"][:3])
    assert got["size"] <= arpplan.MAX_TARGETS, (addr, got["size"])
    assert "10.0.3.20" in got["targets"] or any(ipaddress.ip_address("10.0.3.20") in ipaddress.ip_network(t) for t in got["targets"] if "/" in t), (addr, got)
got = search("10.0.0.2/8")
assert "10.200.1.5" not in got["targets"], "a /8 is read as the /16 around this machine (scan/arpplan.py): a device outside it is not asked"

# 3) the plan failing: only the own /24
real_plan = arpplan.plan
arpplan.plan = lambda *a, **k: 1 / 0
try:
    got = search("10.0.0.2/8")
finally:
    arpplan.plan = real_plan
assert not got["localnet"] and got["targets"] == ["10.0.0.0/24"], got

print("check_quick_scan_large_network: ok")
