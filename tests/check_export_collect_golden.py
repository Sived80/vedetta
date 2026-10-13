"""Golden-master test of export_zip._collect (everything that identifies the household, gathered before the export is masked): 200 generated situations
(devices on the board, DHCP leases, mDNS cards, Home Assistant registry cards, areas, public addresses and hops, odd and missing values) must leave the
Anonymizer in exactly the state stored in tests/golden/export_collect.json (its tables, and what it makes of a text that names everything), written from the
code as it was before the function was split.   Regenerate only on purpose:  COLLECT_GOLDEN_UPDATE=1 python tests/check_export_collect_golden.py"""
import json
import os
import random
import subprocess
import sys
from pathlib import Path

if os.environ.get("PYTHONHASHSEED") != "0":      # the rooms are numbered in the order of a set of strings, which changes with the hash seed: pin it
    sys.exit(subprocess.call([sys.executable] + sys.argv, env={**os.environ, "PYTHONHASHSEED": "0"}))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_zip  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "export_collect.json"
N = 200
rng = random.Random(97531)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def mac():
    return pick([None, "", "f0:18:98:%02x:%02x:%02x" % (rng.randrange(256), rng.randrange(256), rng.randrange(256)), "AA-BB-CC-%02X-%02X-%02X" % (rng.randrange(256), rng.randrange(256), rng.randrange(256))])


def ip():
    return pick([None, "192.168.%d.%d" % (rng.randrange(3), rng.randrange(1, 250)), "10.0.%d.%d" % (rng.randrange(2), rng.randrange(1, 250)), "172.16.1.%d" % rng.randrange(1, 250), "x"])


NAMES = ["Salotto", "iPhone di Anna", "nas", "Xiaomi-14", "Luce cucina", None, "", "Mario's PC", "Hue Bridge", "shelly1-8CAA11"]
AREAS = ["Cucina", "Sala", None, "Studio", "Garage"]


def device():
    d = {"ip": ip(), "mac": mac(), "name": pick(NAMES), "brand": pick([None, "Acme", "Signify"])}
    if rng.random() < 0.2:
        d["name"] = d["ip"]
    if rng.random() < 0.15:
        d["type"] = pick(["light", "phone", "nonsense", None])
    return d


def card():
    return {"name": pick(NAMES), "model": pick([None, "M1"]), "manufacturer": pick([None, "Acme", "Signify"]), "area": pick(AREAS),
            "entry_titles": [pick(["Hue Bridge", "Shelly", None]) for _ in range(rng.randrange(0, 3))]}


def situation():
    for table in (dhcp.seen, mdns_listener.by_mac, mdns_listener.by_ip, ha_registry._state["by_mac"], ha_registry._state["by_ip"]):
        table.clear()
    for _ in range(rng.randrange(0, 5)):
        m = mac()
        if m:
            dhcp.seen[m.lower()] = {"hostname": pick(NAMES)}
    for _ in range(rng.randrange(0, 4)):
        m = mac()
        if m:
            mdns_listener.by_mac[m.lower()] = card()
        i = ip()
        if i:
            mdns_listener.by_ip[i] = card()
    for _ in range(rng.randrange(0, 4)):
        m = mac()
        if m:
            ha_registry._state["by_mac"][m.lower()] = card()
        i = ip()
        if i:
            ha_registry._state["by_ip"][i] = card()
    devices = [device() for _ in range(rng.randrange(0, 8))]
    net = pick([{}, {"public_ip": "93.184.216.%d" % rng.randrange(1, 250), "hops": ["81.2.3.%d" % rng.randrange(1, 250), "8.8.8.8", None]}, {"public_ip": None, "hops": None}])
    roles.snapshot = lambda net=net: {"internet": net}
    return devices


def dump(anon):
    state = {}
    for k, v in sorted(vars(anon).items()):
        if k == "_name_re":
            continue
        state[k] = sorted(v) if isinstance(v, set) else v
    return state


out = []
for _ in range(N):
    devices = situation()
    try:
        anon = export_zip._collect(devices)
        probe = " ".join(str(x) for d in devices for x in (d.get("ip"), d.get("mac"), d.get("name"))) + " Salotto Cucina 93.184.216.5 8.8.8.8"
        out.append({"state": dump(anon), "masked": anon.text(probe)})
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("COLLECT_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y], default=str)[:600])
assert not any("exception" in o for o in out), [o for o in out if "exception" in o][:2]
assert sum(1 for o in out if o["state"]["_macs"]) > 100 and sum(1 for o in out if o["state"]["_areas"]) > 60 and sum(1 for o in out if o["state"]["_public_known"]) > 40, "scenarios too uniform"
print("TUTTO OK")
