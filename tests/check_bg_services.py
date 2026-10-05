"""Full background scan: after the ports, service and operating system are read
only on the open ports (real data from a Fire TV Stick: port 40027 "Amazon FireTV Stick")."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import devices_config, rescan, scanner  # noqa: E402

tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
devices_config.add_devices([{"ip": "10.0.0.103", "name": "Android", "adapter": "generic", "port": 80}])
did = devices_config.load_devices()[0]["id"]


def xml(ports, osname=None):
    p = "".join(f'<port protocol="tcp" portid="{n}"><state state="open"/><service name="{s}"' + (f' product="{prod}"' if prod else "") + ' method="probed" conf="10"/></port>'
                for n, s, prod in ports)
    o = f'<os><osmatch name="{osname}" accuracy="95"/></os>' if osname else ""
    return f'<nmaprun><host><status state="up"/><address addr="10.0.0.103" addrtype="ipv4"/><ports>{p}</ports>{o}</host></nmaprun>'


calls = []


async def fake_nmap(args, semaphore=None):
    calls.append(args)
    if "-sV" in args:   # second phase: only the ports found
        assert args[args.index("-p") + 1] == "5555,8009,40027", args
        return xml([(5555, "adb", "Android Debug Bridge"), (8009, "castv2", None), (40027, "amazon-wplay", "Amazon FireTV Stick")],
                   "Amazon Fire TV or Kindle Paperwhite")
    return xml([(5555, "freeciv", None), (8009, "ajp13", None), (40027, "unknown", None), (55443, "unknown", None)])


async def fake_refresh(*a, **k):
    return None

scanner._run_nmap = fake_nmap
rescan.state.refresh_device = fake_refresh
asyncio.run(rescan._full_ports_background(did, "10.0.0.103"))
info = devices_config.load_devices()[0]["scan_info"]
labels = [p["label"] for p in info["ports"]]
assert any("40027" in l and "Amazon FireTV Stick" in l for l in labels), labels
assert "os" not in info          # the operating system is neither read nor saved
assert len(calls) == 2
print("TUTTO OK")
