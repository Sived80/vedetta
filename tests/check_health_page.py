"""The findings as the page draws them (ha/health_page.py): who (name and IP of each device, the MAC only for a device that has no card), what, when and how many times, and nothing that is not needed.
Only the active findings; one entry for each conflicting address; a device that is no longer known is left out; the order is the worst first, then the newest. The sources are handed in, nothing is read from the network."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import health_page  # noqa: E402
from app.health.engine import Finding  # noqa: E402

TILES = {"H20": "addr", "H05": "boot", "H06": "drop", "H07": "lat"}
DEVICES = [
    {"id": "d1", "name": "Stampante studio", "ip": "192.168.1.50", "mac": "AA:BB:CC:00:00:01"},
    {"id": "d2", "name": "Tablet Marco", "ip": "192.168.1.60", "mac": "aa:bb:cc:00:00:02"},
    {"id": "cam", "name": "Presa cucina", "ip": "192.168.1.37", "mac": "aa:bb:cc:00:00:03"},
    {"id": "gw", "name": "Router", "ip": "192.168.1.1", "mac": "aa:bb:cc:00:00:04"},
    {"id": "noname", "name": "", "ip": "192.168.1.77", "mac": "aa:bb:cc:00:00:05"},
]
CONFLICTS = {"192.168.1.50": ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:99"]}


def finding(rule, subject, evidence, state="active", severity="warning", first=100.0, last=200.0, hits=3, shadow=True):
    return Finding(rule, subject, state, severity, first, last, hits, evidence, shadow)


def build(findings, conflicts=CONFLICTS, gateway="192.168.1.1", devices=DEVICES):
    return health_page.build(findings, TILES, devices, conflicts, gateway)


# --- an address in conflict: one entry for each address, a known device by name, an unknown one by the MAC (the only thing that tells it apart)
out = build([finding("H20", "lan", {"ips": 1, "macs": 2})])
assert len(out) == 1 and out[0]["id"] == "H20:192.168.1.50" and out[0]["tile"] == "addr" and out[0]["lv"] == "warn", out
assert out[0]["devs"] == [{"id": "d1", "name": "Stampante studio", "ip": "192.168.1.50"}, {"name": None, "ip": "192.168.1.50", "mac": "aa:bb:cc:00:00:99"}], out[0]["devs"]
assert (out[0]["since"], out[0]["last"], out[0]["hits"], out[0]["shadow"]) == (100.0, 200.0, 3, True), out[0]
assert build([finding("H20", "lan", {})], conflicts={}) == [], "the conflict has gone since: nothing to show"
two = build([finding("H20", "lan", {})], conflicts={"10.0.0.5": ["aa:bb:cc:00:00:02"], "10.0.0.6": ["aa:bb:cc:00:00:03"]})
assert sorted(e["id"] for e in two) == ["H20:10.0.0.5", "H20:10.0.0.6"] and two[0]["devs"][0]["name"] in ("Tablet Marco", "Presa cucina")

# --- a device that restarts: the card of the device, the counts of the evidence
out = build([finding("H05", "cam", {"drops": 11, "period_s": 600, "cv": 0.1})])
assert out[0]["id"] == "H05:cam" and out[0]["tile"] == "boot" and out[0]["devs"] == [{"id": "cam", "name": "Presa cucina", "ip": "192.168.1.37"}], out
assert out[0]["data"] == {"drops": 11, "period_s": 600, "cv": 0.1}, out[0]["data"]
assert build([finding("H05", "gone", {"drops": 11})]) == [], "a device that is not known any more leaves nothing to show"

# --- devices that drop together: the known ones, in the order of the evidence; the id list does not travel to the page
out = build([finding("H06", "lan", {"devices": 3, "of": 20, "ids": ["d2", "gone", "d1"]})])
assert [d["name"] for d in out[0]["devs"]] == ["Tablet Marco", "Stampante studio"] and out[0]["tile"] == "drop", out
assert out[0]["data"] == {"devices": 3, "of": 20} and "ids" not in out[0]["data"], out[0]["data"]

# --- the latency of the gateway: the card that has the address of the default route
out = build([finding("H07", "gateway", {"from_ms": 0.5, "to_ms": 8.0})])
assert out[0]["tile"] == "lat" and out[0]["devs"] == [{"id": "gw", "name": "Router", "ip": "192.168.1.1"}], out
assert build([finding("H07", "gateway", {"from_ms": 0.5, "to_ms": 8.0})], gateway=None) == [], "no default route, no gateway"

# --- a device with no name is shown by its address only, and its MAC is not shown: the card (its id opens it) is the place for it
out = build([finding("H05", "noname", {"drops": 6, "period_s": 300, "cv": 0.0})])
assert out[0]["devs"] == [{"id": "noname", "name": None, "ip": "192.168.1.77"}], out[0]["devs"]

# --- only the active ones, the worst first and then the newest; critical is drawn as «bad»
mixed = build([finding("H05", "cam", {"drops": 6}, state="tentative"), finding("H05", "cam", {"drops": 7}, first=50.0),
               finding("H06", "lan", {"devices": 5, "of": 9, "ids": ["d1", "d2"]}, first=300.0), finding("H07", "gateway", {"from_ms": 1, "to_ms": 9}, severity="critical", first=10.0)])
assert [e["id"] for e in mixed] == ["H07:gateway", "H06:lan", "H05:cam"] and [e["lv"] for e in mixed] == ["bad", "warn", "warn"], mixed
assert build([]) == [] and build([finding("H99", "x", {})]) == [], "a rule that is not in the matrix is not drawn"

print("check_health_page OK")
