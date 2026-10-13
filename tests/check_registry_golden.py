"""Golden-master test of ha_registry.build_index (the join of the Home Assistant registries by MAC and by address): 300 generated registries (seeded, always
the same) with the awkward cases (disabled devices and entities, devices made by Vedetta itself, MACs written in several ways or invalid, configuration
addresses that are IPs, host names or shared by several devices, names chosen by the user, integrations that are only 'mqtt') must give exactly the output
stored in tests/golden/registry_index.json, written from the code as it was before the function was split.
Regenerate only on purpose:  REGISTRY_GOLDEN_UPDATE=1 python tests/check_registry_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "registry_index.json"
N = 300
rng = random.Random(4242)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def mac():
    raw = [rng.randrange(256) for _ in range(6)]
    style = rng.randrange(6)
    if style == 0:
        return ":".join(f"{b:02X}" for b in raw)
    if style == 1:
        return "-".join(f"{b:02x}" for b in raw)
    if style == 2:
        return ":".join(f"{b:02x}" for b in raw)
    if style == 3:
        return ":".join(f"{b:02x}" for b in raw[:5])           # too short: invalid
    if style == 4:
        return "".join(f"{b:02x}" for b in raw)                # no separators: invalid
    return " " + ":".join(f"{b:02x}" for b in raw) + " "


def registry(i):
    areas = [{"area_id": f"a{k}", "name": pick(["Cucina", "Sala", "Studio", None, "Garage"])} for k in range(rng.randrange(0, 4))]
    entries = [{"entry_id": f"e{k}", "domain": pick(["mqtt", "hue", "shelly", "fritz", "cast", "mobile_app", None]), "title": pick(["Hue Bridge", "Shelly", "MQTT", "FRITZ!Box", None, "Chromecast"])}
               for k in range(rng.randrange(1, 5))]
    shared_url = f"http://10.0.{i % 200}.{rng.randrange(1, 250)}:3000/"
    devices, entities = [], []
    for k in range(rng.randrange(1, 16)):
        did = f"d{i}-{k}"
        conns = [["mac", mac()] for _ in range(rng.randrange(0, 3))] + ([["upnp", "uuid"]] if rng.random() < 0.2 else []) + ([["mac"]] if rng.random() < 0.05 else [])
        ident = [[pick(["mqtt", "hue", "shelly"]), pick(["vedetta_hub", "vedetta_x1", "abc", "123"])]] if rng.random() < 0.6 else []
        url = pick([None, shared_url, f"http://192.168.{i % 200}.{rng.randrange(1, 250)}/", "http://router.local/", "https://nas:5001", "", "http://999.1.1.1/", None])
        devices.append({
            "id": did, "name": pick([None, "Lampada", "shelly1-8CAA11", "Router"]), "name_by_user": pick([None, None, "Luce studio", ""]),
            "manufacturer": pick([None, "Acme", "Signify", "Shelly"]), "model": pick([None, "M1", "SHSW-1"]), "area_id": pick([None, "a0", "a1", "zz"]),
            "disabled_by": pick([None, None, None, None, "user"]), "connections": conns, "identifiers": ident,
            "configuration_url": url, "sw_version": pick([None, "1.0", "2.3.4"]),
            "config_entries": [pick(entries)["entry_id"] for _ in range(rng.randrange(0, 3))] + ([] if rng.random() < 0.9 else ["ghost"]),
        })
        for j in range(rng.randrange(0, 4)):
            entities.append({"device_id": did, "entity_id": pick(["light.a", "sensor.b", "device_tracker.c", "switch.d", ""]), "name": pick([None, "Presa", "Temperatura"]),
                             "original_name": pick([None, "Original", "Sensor"]), "disabled_by": pick([None, None, None, "integration"])})
    entities.append({"device_id": None, "entity_id": "sensor.orphan", "name": "x"})
    return devices, entities, areas, entries


out = []
for i in range(N):
    d, e, a, en = registry(i)
    out.append(ha_registry.build_index(d, e, a, en))
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("REGISTRY_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "registry %d differs: %s" % (i, json.dumps([x, y], default=str)[:500])
assert sum(len(o["by_mac"]) for o in out) > 300 and sum(len(o["by_ip"]) for o in out) > 100, "scenarios too uniform"
assert any(c["name_by_user"] for o in out for c in o["by_mac"].values()) and any(c["area"] for o in out for c in o["by_mac"].values())
print("TUTTO OK")
