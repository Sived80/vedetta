"""Characterization of the commands that name the network interface, before the work on more networks (decision D2: the only change allowed to arp_scan is an optional
interface parameter whose default keeps everything as it is). Asserts the commands of today, word by word, with the interface of lan_iface():
arp-scan on the whole network (--localnet, no standard input) and on a list (--file=-, the targets on the standard input, one per line), with and without --interval;
`ip -4 -o neigh show dev <if>`; the MAC of the own host read from /sys/class/net/<if>/address; the nmap prerule scripts with `-e <if>`. No packet: fake processes.
    python tests/check_arp_scan_interface_args.py"""
import asyncio
import io
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_arp, scan_protocols  # noqa: E402

IFACE = "lan9"
CALLS: list = []


class FakeProc:
    returncode = 0

    def __init__(self, out: str):
        self.out = out

    async def communicate(self, data=None):
        CALLS.append(("stdin", data))
        return self.out.encode(), b""

    def kill(self):
        pass

    async def wait(self):
        return 0


def fake_exec(out: str):
    async def run(*args, **kwargs):
        CALLS.append(("exec", args, kwargs.get("stdin") is not None))
        return FakeProc(out)
    return run


scan_arp.registry.main_interface = lambda: IFACE
scan_arp.asyncio.create_subprocess_exec = fake_exec("10.0.0.10\taa:bb:cc:00:00:0a\tMaker A\n")

# 1) arp-scan on the whole network
CALLS.clear()
hosts = asyncio.run(scan_arp.arp_scan())
assert CALLS[0] == ("exec", ("arp-scan", "--interface=lan9", "-x", "--localnet"), False), CALLS
assert CALLS[1] == ("stdin", None), CALLS
assert [h["ip"] for h in hosts] == ["10.0.0.10"], hosts

# 2) arp-scan on a list, with a pause between packets
CALLS.clear()
asyncio.run(scan_arp.arp_scan(["10.0.0.10", "10.0.0.32/29"], interval_ms=20))
assert CALLS[0] == ("exec", ("arp-scan", "--interface=lan9", "-x", "--file=-", "--interval=20"), True), CALLS
assert CALLS[1] == ("stdin", b"10.0.0.10\n10.0.0.32/29"), CALLS

# 3) an empty list counts as "the whole network"
CALLS.clear()
asyncio.run(scan_arp.arp_scan([]))
assert CALLS[0][1][-1] == "--localnet", CALLS

# 4) the neighbour table of the same interface
scan_arp.asyncio.create_subprocess_exec = fake_exec("10.0.0.11 lladdr aa:bb:cc:00:00:0b REACHABLE\n")
CALLS.clear()
asyncio.run(scan_arp.neighbors("10.0.0.0/24"))
assert CALLS[0] == ("exec", ("ip", "-4", "-o", "neigh", "show", "dev", "lan9"), False), CALLS

# 5) the own host: the MAC of the same interface
OPENED: list = []


def fake_open(path, *a, **k):
    OPENED.append(path)
    return io.StringIO("02:00:5e:00:00:02\n")


scan_arp.open = fake_open
own = scan_arp.own_host("10.0.0.2", [])
del scan_arp.open
assert OPENED == ["/sys/class/net/lan9/address"], OPENED
assert own == {"ip": "10.0.0.2", "mac": "02:00:5E:00:00:02", "vendor": None}, own

# 6) the nmap prerule scripts (SSDP, IGMP...) on the same interface
NMAP: list = []


async def fake_nmap(args, semaphore=None):
    NMAP.append(args)
    return "<nmaprun/>"


scan_protocols._run_nmap = fake_nmap
assert asyncio.run(scan_protocols.ssdp_scan(timeout=6)) == {}
assert NMAP[0] == ["-sn", "--script", "broadcast-upnp-info", "-e", "lan9", "--host-timeout", "6s", "127.0.0.1"], NMAP

print("check_arp_scan_interface_args: ok")
