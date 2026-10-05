"""Check of new devices, settings and the Wake-on-LAN magic packet.
In the container: python tests/check_newdevices.py
Locally (Windows) it also works without zoneinfo: if app.applog cannot be
imported it is simulated. Uses a temporary database and config folder.
With "python - < file" the current folder must be the project root."""
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    import logging
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app import newdevices, settings, wol
from app.history import History

tmp = Path(tempfile.mkdtemp())
hist = History(tmp / "t.db")


def arp(*pairs):
    return {ip: {"ip": ip, "mac": mac, "vendor": None} for ip, mac in pairs}


def run(hosts, cfg_ips=(), cfg_macs=(), dhcp_seen=None, skip=()):
    obs = newdevices.observed_macs(hosts, dhcp_seen or {}, set(skip))
    return newdevices.evaluate(obs, set(cfg_ips), set(cfg_macs), hist=hist)


A, B, C = "AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03"

# 1) empty ARP on the first cycle: the baseline waits
assert run({}) == ([], [])
assert hist.meta_get(newdevices.BASELINE_KEY) is None

# 2) baseline: everything 'known', no alert
fresh, cur = run(arp(("10.0.0.1", A), ("10.0.0.2", B)))
assert fresh == [] and cur == []
assert {r["status"] for r in hist.known_all().values()} == {"known"}
assert hist.meta_get(newdevices.BASELINE_KEY) is not None
print("ok: baseline senza avvisi")

# 3) same MACs: nothing new
assert run(arp(("10.0.0.1", A), ("10.0.0.2", B)))[0] == []

# 4) never-seen MAC: a single alert, not repeated on the next cycle
hosts = arp(("10.0.0.1", A), ("10.0.0.3", C))
fresh, cur = run(hosts, dhcp_seen={C.lower(): {"hostname": "tv-salotto"}})
assert [f["mac"] for f in fresh] == [C] and [c["mac"] for c in cur] == [C], (fresh, cur)
assert cur[0]["hostname"] == "tv-salotto" and cur[0]["ip"] == "10.0.0.3"
fresh, cur = run(hosts)
assert fresh == [] and len(cur) == 1, "un MAC gia' 'new' non va riavvisato"
# the IP is updated to the last one seen
fresh, cur = run(arp(("10.0.0.9", C)))
assert fresh == [] and cur[0]["ip"] == "10.0.0.9"
print("ok: nuovo MAC -> un solo avviso, IP aggiornato")

# 4b) a MAC known only from DHCP (not in ARP) is not "present"
obs = newdevices.observed_macs(arp(("10.0.0.1", A)), {"AA:BB:CC:DD:EE:01".lower(): {"hostname": "x"}}, set())
assert list(obs) == [A], obs
newdevices.sync_present({C})
assert [d["mac"] for d in newdevices.list_new(hist)] == [C]
newdevices.sync_present(set())
assert newdevices.list_new(hist) == []
print("ok: DHCP da solo non vale come presenza, sync_present")
run(arp(("10.0.0.9", C)))  # restore presence for the following tests

# 5) ignore: it disappears from 'new' and does not alert again
assert newdevices.ignore(["00:00:00:00:00:00"], hist) == cur  # invalid MAC: no-op
assert newdevices.ignore([C], hist) == []
assert hist.known_all()[C]["status"] == "ignored"
assert run(arp(("10.0.0.9", C)))[0] == []
D = "AA:BB:CC:00:00:04"
E = "AA:BB:CC:00:00:05"
run(arp(("10.0.0.4", D), ("10.0.0.5", E)))
assert len(newdevices.list_new(hist)) == 2
assert newdevices.ignore(None, hist) == [] and newdevices.ignore([], hist) == []
print("ok: ignora (uno, tutti)")

# 6) 'new' that becomes configured -> 'known'; new MAC already configured -> never 'new'
F, G = "AA:BB:CC:00:00:06", "AA:BB:CC:00:00:07"
fresh, _ = run(arp(("10.0.0.6", F)))
assert [f["mac"] for f in fresh] == [F]
fresh, cur = run(arp(("10.0.0.6", F)), cfg_ips={"10.0.0.6"})
assert cur == [] and hist.known_all()[F]["status"] == "known"
fresh, cur = run(arp(("10.0.0.7", G)), cfg_macs={G})
assert fresh == [] and hist.known_all()[G]["status"] == "known"
print("ok: passaggio a known")

# 7) invalid MACs, multicast and own IP ignored
H = "AA:BB:CC:00:00:08"
fresh, _ = run(arp(("10.0.0.20", "00:00:00:00:00:00"), ("10.0.0.21", "01:00:5E:00:00:01"),
                   ("10.0.0.22", "garbage"), ("10.0.0.23", H)), skip={"10.0.0.23"})
assert fresh == []
print("ok: MAC non validi e IP proprio ignorati")

# 8) settings: defaults, update, unknown keys, wrong type
settings.SETTINGS_PATH = tmp / "settings.json"
assert settings.load() == {"alerts": True, "poll_interval": 30, "miss_limit": 3}
assert settings.update({"alerts": False, "altro": 1}) == {"alerts": False, "poll_interval": 30, "miss_limit": 3}
assert settings.load() == {"alerts": False, "poll_interval": 30, "miss_limit": 3} and "altro" not in settings.SETTINGS_PATH.read_text()
try:
    settings.update({"alerts": "si"})
    raise SystemExit("doveva rifiutare un valore non booleano")
except ValueError:
    pass
print("ok: impostazioni")

# 9) magic packet: 102 bytes, 6 x FF + 16 x MAC
for mac in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff"):
    p = wol.build_magic_packet(mac)
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:] == bytes.fromhex("AABBCCDDEEFF") * 16
for bad in (None, "", "AA:BB", "GG:BB:CC:DD:EE:FF", "AABBCCDDEEFF"):
    assert not wol.is_valid_mac(bad)
print("ok: magic packet (102 byte)")

print("TUTTO OK")
