"""Golden-master test of ha_registry.choose_name (name and source from a Home Assistant record: the name chosen by the user in HA first, else the device name or the first usable
integration title): 5000 generated records - no record, name chosen by the user or not, placeholder and technical names, a name that cleans to nothing (a bare IP), names with
spaces and an embedded address, generic integration titles in any case and with spaces, empty and None titles, a missing name, a missing or None title list - must give exactly
the (name, source) pairs (or the exception) stored in tests/golden/choose_name_ha.json, written from the code as it was before the function was split into small checks.
Regenerate only on purpose:  CHOOSENAMEHA_GOLDEN_UPDATE=1 python tests/check_choose_name_ha_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_registry  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "choose_name_ha.json"
N = 5000
rng = random.Random(1357)
NAMES = [None, "", "   ", "Android", "iPhone", "Android_MGDZ1OUL", "shelly1-8CAA12", "Lampada soggiorno", "  Living   Room  ", "ABC@ES", "192.168.1.5", "Sensor (192.168.1.7)",
         "amzn.dmgr.05837F86", "Cucina.local", "Studio", "Termostato"]
TITLES = [None, "", " ", "MQTT", "mqtt", " Shelly ", "Fritz!Box", "Home Assistant", "Tasmota", "ESPHome", "Mobile App", "Android", "iPhone", "Garage", "Hue Bridge", "192.168.1.9", "ABC@ES",
          "shelly1-8CAA12"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def card():
    r = rng.random()
    if r < 0.05:
        return pick([None, {}])
    c = {}
    if rng.random() < 0.95:
        c["name"] = pick(NAMES)
    if rng.random() < 0.9:
        c["name_by_user"] = pick([True, False, None, 1, 0])
    mode = pick(["list", "list", "list", "none", "empty", "missing"])
    if mode == "list":
        c["entry_titles"] = [pick(TITLES) for _ in range(rng.randrange(1, 5))]
    elif mode == "none":
        c["entry_titles"] = None
    elif mode == "empty":
        c["entry_titles"] = []
    return c


out = []
for _ in range(N):
    c = card()
    try:
        r = list(ha_registry.choose_name(c))
    except Exception as exc:
        r = {"exception": type(exc).__name__}
    out.append([c, r])
out = json.loads(json.dumps(out))
if os.environ.get("CHOOSENAMEHA_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [o[1] for o in out]
src = {}
for r in res:
    if isinstance(r, list):
        src[r[1]] = src.get(r[1], 0) + 1
assert set(src) == {"ha_user", "ha", None} and min(src.values()) > 200, src
assert any(r == [None, "ha_user"] for r in res) and any(isinstance(r, dict) for r in res) and sum(1 for r in res if isinstance(r, dict)) < 100
c_title = [o for o in out if isinstance(o[1], list) and o[1][1] == "ha" and o[0].get("name") != o[1][0]]
assert len(c_title) > 300, "titles are never the source of the name"
print("TUTTO OK")
