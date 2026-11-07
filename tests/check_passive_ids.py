"""Characterization of the ids of the devices Home Assistant sees ("passive" devices), before the work on more networks (they may later sit in the same archive as the cards
Vedetta scans): the id is "ha-" + the 12 hexadecimal digits of the MAC, it goes back to the MAC, and it can never be the id of a scanned card ("scan-<ip>" or an explicit
one with -2, -3); a value that is not a passive id gives no MAC. presence_changes is pure: it lists only the devices whose presence differs from the one last written,
with the MAC in upper case, and changes neither of its inputs. 2000 MACs and addresses with a fixed seed.
    python tests/check_passive_ids.py"""
import copy
import os
import random
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha.passive_service import presence_changes  # noqa: E402
from app.storage import passive_store as ps  # noqa: E402
from app.storage.devices_config import _unique_device_id  # noqa: E402

assert ps.id_of("AA:BB:CC:00:00:0A") == "ha-aabbcc00000a"
assert ps.mac_of("ha-aabbcc00000a") == "aa:bb:cc:00:00:0a"
for bad in ("scan-10-0-0-10", "ha-", "ha-aabbcc00000", "ha-aabbcc00000g", "ha-AABBCC00000A", "", None, "lamp"):
    assert ps.mac_of(bad) is None, bad

rng = random.Random(20261107)
passive, scanned = set(), set()
for _ in range(2000):
    mac = ":".join("%02x" % rng.randrange(256) for _ in range(6))
    pid = ps.id_of(mac)
    assert ps.is_passive_id(pid) and ps.mac_of(pid) == mac, (mac, pid)
    passive.add(pid)
    ip = "10.%d.%d.%d" % (rng.randrange(256), rng.randrange(256), rng.randrange(1, 255))
    sid = _unique_device_id({"ip": ip}, scanned)
    assert not ps.is_passive_id(sid), sid
    scanned.add(sid)
assert not passive & scanned

adopted = {"aa:bb:cc:00:00:0a": {"row": {"ip": "10.0.20.30", "online": True}},
           "aa:bb:cc:00:00:0b": {"row": {"ip": "10.0.20.31", "online": False}},
           "aa:bb:cc:00:00:0c": {"row": {"ip": "10.0.20.32"}}}
last = {"ha-aabbcc00000a": True, "ha-aabbcc00000b": True}
before = (copy.deepcopy(adopted), dict(last))
out = presence_changes(adopted, last)
assert sorted(out) == [("ha-aabbcc00000b", "10.0.20.31", "AA:BB:CC:00:00:0B", False), ("ha-aabbcc00000c", "10.0.20.32", "AA:BB:CC:00:00:0C", False)], out
assert (adopted, last) == before, "presence_changes must not change its inputs"
assert presence_changes({}, last) == [] and presence_changes(adopted, {"ha-aabbcc00000a": True, "ha-aabbcc00000b": False, "ha-aabbcc00000c": False}) == []

print("check_passive_ids: ok")
