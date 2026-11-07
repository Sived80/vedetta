"""Characterization of how the gateway and the network interface are read today, before the work on more networks: both are read ONCE and kept for the whole run,
so after a change of network (the field case of 05/11) the page keeps the old gateway until a restart. Asserts what the code does now - the planned fix (a reading
with an expiry) will change this test on purpose, in the same commit:
- default_gateway(): the first good reading of /proc/net/route is kept, a later change of the file is ignored; a reading with no gateway is not kept (the next one tries
  again); another file (the export reads a copy) is never kept and never uses what is kept;
- lan_iface(): the interface of the default route with the lowest metric, kept after the first call; the option VEDETTA_IFACE wins when it is a valid name.
Fake route files in a temporary folder.
    python tests/check_gateway_cache.py"""
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ["VEDETTA_DATA_DIR"] = str(TMP)
os.environ.pop("VEDETTA_IFACE", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import iface  # noqa: E402
from app.recognition import identity  # noqa: E402

HEAD = "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"


def route(dev: str, gw_hex: str, metric: int = 0) -> str:
    return f"{dev}\t00000000\t{gw_hex}\t0003\t0\t0\t{metric}\t00000000\t0\t0\t0\n"


GW_A = "0100000A"      # 10.0.0.1 (little endian)
GW_B = "0132A8C0"      # 192.168.50.1
LOCAL = "lan9\t0000000A\t00000000\t0001\t0\t0\t0\t00FFFFFF\t0\t0\t0\n"   # 10.0.0.0/24, no gateway

route_file = TMP / "route"
SYSTEM = "/proc/net/route"
real_read = identity._read_gateway
identity._read_gateway = lambda path: real_read(str(route_file) if path == SYSTEM else path)

# 1) gateway: no default route yet -> None, and nothing is kept
route_file.write_text(HEAD + LOCAL)
assert identity.default_gateway() is None
route_file.write_text(HEAD + LOCAL + route("lan9", GW_A))
assert identity.default_gateway() == "10.0.0.1", "a reading with no gateway must not be kept"

# 2) the first good reading is kept: a new network is not seen
route_file.write_text(HEAD + route("lan9", GW_B))
assert identity.default_gateway() == "10.0.0.1", "today the gateway is read once"

# 3) another file is read every time and does not touch what is kept
other = TMP / "copy"
other.write_text(HEAD + route("lan9", GW_B))
assert identity.default_gateway(str(other)) == "192.168.50.1"
assert identity.default_gateway() == "10.0.0.1"

# 4) the interface: lowest metric, kept after the first call
iface._ROUTE_FILE = str(route_file)
iface.lan_iface.cache_clear()
route_file.write_text(HEAD + route("wan0", GW_A, 200) + route("lan9", GW_A, 100))
assert iface.lan_iface() == "lan9"
route_file.write_text(HEAD + route("lan7", GW_B))
assert iface.lan_iface() == "lan9", "today the interface is read once"
iface.lan_iface.cache_clear()
assert iface.lan_iface() == "lan7"

# 5) no default route -> the fallback; the option wins when valid, is ignored when not
iface.lan_iface.cache_clear()
route_file.write_text(HEAD + LOCAL)
assert iface.lan_iface() == iface.FALLBACK == "eth0"
os.environ["VEDETTA_IFACE"] = "enp0s18.20"
iface.lan_iface.cache_clear()
assert iface.lan_iface() == "enp0s18.20"
os.environ["VEDETTA_IFACE"] = "-bad name"
iface.lan_iface.cache_clear()
route_file.write_text(HEAD + route("lan9", GW_A))
assert iface.lan_iface() == "lan9"

print("check_gateway_cache: ok")
