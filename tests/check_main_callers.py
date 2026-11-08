"""The places that ask for the main network (network and own address) ask networks.registry.main(), and get what the host says: with a fake
`ip addr`, each one sees 192.168.50.0/24 and 192.168.50.7 exactly as before the move from netutil.get_local_network, and the registry is asked
(a spy counts the calls). One block per place, added with the commit that moves it. Invented private addresses only.
    python tests/check_main_callers.py"""
import asyncio
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import arpview, netutil  # noqa: E402
from app.newdevicewatch import NewDeviceWatch  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.scan import discovery, pipeline, pipeline_plan, scan_arp, scanner  # noqa: E402
from app.networks import registry  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

NET, OWN = "192.168.50.0/24", "192.168.50.7"


class FakeProc:
    returncode = 0

    async def communicate(self, data=None):
        return b"3: lan9    inet 192.168.50.7/24 brd 192.168.50.255 scope global lan9\n", b""


async def fake_exec(*args, **kwargs):
    return FakeProc()


netutil.asyncio.create_subprocess_exec = fake_exec
netutil.lan_iface = lambda: "lan9"
ASKED: list = []
_real_main = registry.main


async def spy_main():
    ASKED.append(1)
    return await _real_main()


registry.main = spy_main


def asked_once_by(label, fn):
    """Runs fn (a coroutine function), checks it asked the registry and returns what it gave."""
    before = len(ASKED)
    out = asyncio.run(fn())
    assert len(ASKED) > before, f"{label}: the registry was not asked"
    return out


# arpview: the network of the continuous ARP view
assert asked_once_by("arpview", arpview.ArpView(lambda *a: None).network) == (NET, OWN)

# newdevicewatch: our own address, left out of the comparison of new devices
watch = NewDeviceWatch.__new__(NewDeviceWatch)
watch.own_ip = None
assert asked_once_by("newdevicewatch", watch._skip_ips) == {OWN}

# roles: our own address, left out of the UPnP search
SSDP_FOR: list = []


async def fake_ssdp(own_ip, skip=frozenset()):
    SSDP_FOR.append(own_ip)
    return []


async def fake_arp_snapshot():
    return {}


roles.discovery.ssdp_devices = fake_ssdp
roles.devices_config.load_devices = lambda: []
roles._rt.dhcp_discover = None


async def discovery_jobs():
    jobs, _, own_ip = await roles._start_discovery_jobs(type("S", (), {"arp_snapshot": staticmethod(fake_arp_snapshot)})())
    await asyncio.gather(*jobs)
    return own_ip


assert asked_once_by("roles", discovery_jobs) == OWN and SSDP_FOR == [OWN], SSDP_FOR

# device_routes: the broadcast address of the network for Wake-on-LAN
assert asked_once_by("device_routes", device_routes._broadcast_targets) == ["255.255.255.255", "192.168.50.255"]

# pipeline: the first search (the network whose neighbours are added, issue #35)
NEIGH_FOR: list = []


async def fake_arp_scan(targets=None):
    return []


async def fake_neighbors(net=None):
    NEIGH_FOR.append(net)
    return []


scanner.arp_scan, scanner.neighbors = fake_arp_scan, fake_neighbors
asked_once_by("pipeline", pipeline.run_initial)
assert NEIGH_FOR == [NET], NEIGH_FOR

# pipeline_plan: our own address for the WS-Discovery search
WSD_FOR: list = []


async def fake_wsd(own_ip):
    WSD_FOR.append(own_ip)
    return {}


discovery.wsd_scan = fake_wsd
asked_once_by("pipeline_plan", pipeline_plan._wsd)
assert WSD_FOR == [OWN], WSD_FOR

# scan_arp: the interface of arp-scan, of the neighbours and of our own MAC is the one of the main network (registry.main_interface)
EXEC: list = []


class QuietProc:
    returncode = 0

    async def communicate(self, data=None):
        return b"", b""

    def kill(self):
        pass

    async def wait(self):
        return 0


async def record_exec(*args, **kwargs):
    EXEC.append(args)
    return QuietProc()


OPENED: list = []


def record_open(path, *args, **kwargs):
    OPENED.append(path)
    raise OSError("not on this computer")


scan_arp.asyncio.create_subprocess_exec = record_exec
scan_arp.open = record_open
asyncio.run(scan_arp.arp_scan())
asyncio.run(scan_arp.neighbors(NET))
scan_arp.own_host(OWN, [])
assert "--interface=lan9" in EXEC[0], EXEC[0]
assert EXEC[1][-2:] == ("dev", "lan9") or "lan9" in EXEC[1], EXEC[1]
assert OPENED == ["/sys/class/net/lan9/address"], OPENED

print("check_main_callers: ok")
