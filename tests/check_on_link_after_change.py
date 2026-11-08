"""Right after a change of network (simulator, S29 run again on 08/11 with K10 and K14): the network kept in memory is up to NET_TTL_S old,
so for minutes the old addresses still looked "on the link" and nmap -PR sent its default probes to them (ICMP timestamp, SYN 443).
What is on the link is read from the kernel's routes (/proc/net/route: a route with no gateway on the main interface), which change the
moment the address changes; the network kept by the ARP view is read again at once when it is no longer one of those routes.
Fake route files in a temporary folder. Invented private addresses only.
    python tests/check_on_link_after_change.py"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["VEDETTA_DATA_DIR"] = str(TMP)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import arpview, netutil  # noqa: E402
from app.networks import host_read, registry  # noqa: E402

HEAD = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
OLD = "lan9\t0000A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"           # 192.168.0.0/24 on lan9, no gateway
NEW = "lan9\t0032A8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"           # 192.168.50.0/24
VLAN = "lan9.60\t003CA8C0\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"       # 192.168.60.0/24 on a VLAN of the host
DEFAULT_NEW = "lan9\t00000000\t0132A8C0\t0003\t0\t0\t0\t00000000\t0\t0\t0\n"   # default route via 192.168.50.1
route = TMP / "route"
registry.ROUTE_FILE = str(route)
netutil.lan_iface = lambda: "lan9"

# the reader: the routes with no gateway on one interface, None when the file cannot be read
route.write_text(HEAD + OLD + VLAN)
assert [str(n) for n in host_read.read_on_link("lan9", str(route))] == ["192.168.0.0/24"]
assert host_read.read_on_link("lan9", str(TMP / "missing")) is None

# on_link follows the routes, not the network kept in memory
netutil.last_network = "192.168.0.0/24"                 # what was read before the change
route.write_text(HEAD + NEW + DEFAULT_NEW)              # the change: the old route is gone
assert not registry.on_link("192.168.0.20"), "an old address is no longer on the link, even if the network in memory is still the old one"
assert registry.on_link("192.168.50.20")
assert not registry.on_link("192.168.60.5") and not registry.on_link("x") and not registry.on_link(None)
# no route file (another system): the network in memory is used, as before
registry.ROUTE_FILE = str(TMP / "missing")
assert registry.on_link("192.168.0.20") and not registry.on_link("192.168.50.20")
registry.ROUTE_FILE = str(route)

# the ARP targets follow the routes too
assert registry.arp_targets(["192.168.0.20", "192.168.50.20", "192.168.60.5"], "192.168.0.0/24") == ["192.168.50.20"]

# the ARP view reads its network again at once when the kept one is no longer a route of the interface
READS: list = []
answer = {"net": ("192.168.0.0/24", "192.168.0.7")}


async def fake_net():
    READS.append(1)
    return answer["net"]


netutil.get_local_network = fake_net
route.write_text(HEAD + OLD)
view = arpview.ArpView(lambda *a: None)
assert asyncio.run(view.network()) == ("192.168.0.0/24", "192.168.0.7") and len(READS) == 1
assert asyncio.run(view.network()) == ("192.168.0.0/24", "192.168.0.7") and len(READS) == 1, "kept while it is still a route"
route.write_text(HEAD + NEW + DEFAULT_NEW)
answer["net"] = ("192.168.50.0/24", "192.168.50.7")
assert asyncio.run(view.network()) == ("192.168.50.0/24", "192.168.50.7"), "read again at once after the change"
print("check_on_link_after_change: ok")
