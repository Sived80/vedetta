"""Reference test of the memory of the continuous Bonjour listener (scan/mdns_listener.py): name scoring, an announcement kept by IP until the MAC
is known and then moved under it, better names winning, the memory file (round trip, broken file, unwritable folder), the housekeeping that
ties old cards to a MAC or drops the expired ones, the lookup, the scan_info form, and the start-up with and without zeroconf."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener as ml  # noqa: E402

tmp = Path(tempfile.mkdtemp())
ml.STORE_PATH = tmp / "mdns_seen.json"
macs = {}
ml._mac_for_ip = lambda ip: macs.get(ip)

# the score of a name: a TXT key chosen by the user beats the instance name, a slug is not a name
assert ml.score_name("_hap._tcp", "Lamp", "") == (2, "Lamp"), "a service with a user-chosen name"
assert ml.score_name("_http._tcp", "web", "") == (1, "web")
s, n = ml.score_name("_http._tcp", "web", '"fn=Salotto"')
assert s >= 2 and n == "Salotto"
assert ml.score_name("_http._tcp", "web", '"fn=a1b2c3d4-xyz"') == (1, "web"), "a technical slug is not a name"

# an announcement is remembered by IP, a better name replaces it, the same score lets the latest win, a wrong IP is ignored
ml.record("not-an-ip", "_hap._tcp", "x", "")
assert not ml.by_ip and not ml.by_mac
ml.record("10.0.0.20", "_http._tcp", "first", "", now=1000.0)
ml.record("10.0.0.20", "_hap._tcp", "second", '"md=Bulb" "mf=Acme"', now=1100.0)
card = ml.by_ip["10.0.0.20"]
assert card["name"] == "second" and card["score"] == 2 and card["model"] == "Bulb" and card["manufacturer"] == "Acme"
assert card["services"] == ["_hap._tcp", "_http._tcp"] and card["seen"] == 1100.0
ml.record("10.0.0.20", "_http._tcp", "worse", "", now=1200.0)
assert ml.by_ip["10.0.0.20"]["name"] == "second", "a worse score does not replace the name"
ml.record("10.0.0.20", "_hap._tcp", "third", "", now=1300.0)
assert ml.by_ip["10.0.0.20"]["name"] == "third", "equal score: the most recent wins"
assert ml._dirty is True

# once the MAC is known the card moves under it
macs["10.0.0.20"] = "aa:bb:cc:00:00:20"
ml.record("10.0.0.20", "_hap._tcp", "fourth", "", now=1400.0)
assert "10.0.0.20" not in ml.by_ip and ml.by_mac["aa:bb:cc:00:00:20"]["name"] == "fourth"

# the memory file: round trip, broken file ignored, unwritable folder survived
ml._save()
assert ml._dirty is False and ml.STORE_PATH.exists()
ml.by_mac.clear(); ml.by_ip.clear()
ml._load()
assert ml.by_mac["aa:bb:cc:00:00:20"]["name"] == "fourth"
ml.by_mac.clear()
ml.STORE_PATH.write_text("{ not json", encoding="utf-8")
ml._load()
assert ml.by_mac == {}
good = ml.STORE_PATH
ml.STORE_PATH = tmp / "missing-folder" / "x.json"
ml._save()                                    # no folder: no error
ml.STORE_PATH = good

# lookup by MAC (any writing) or by IP while recent; the scan_info form
ml.by_mac["aa:bb:cc:00:00:30"] = {"name": "Kitchen", "model": "M1", "manufacturer": "Acme", "services": ["_a._tcp", "_b._tcp"], "seen": time.time()}
assert ml.lookup("AA-BB-CC-00-00-30")["name"] == "Kitchen" and ml.lookup(None, "10.9.9.9") is None
ml.by_ip["10.0.0.31"] = {"name": "Old", "seen": time.time() - ml.IP_TTL_S - 10}
ml.by_ip["10.0.0.32"] = {"name": "Recent", "seen": time.time()}
assert ml.lookup(None, "10.0.0.31") is None and ml.lookup("", "10.0.0.32")["name"] == "Recent"
assert ml.as_scan_info(ml.by_mac["aa:bb:cc:00:00:30"]) == {"mdns_name": "Kitchen", "mdns_model": "M1", "mdns_manufacturer": "Acme", "mdns_services": "_a._tcp, _b._tcp"}
assert ml.as_scan_info(None) == {} and ml.as_scan_info({}) == {}

# housekeeping: a card kept by IP is tied to the MAC when ARP knows it (the newer card wins), the expired ones go
ml.by_ip.clear(); ml.by_mac.clear()
now = time.time()
ml.by_ip.update({"10.0.0.40": {"name": "new", "seen": now}, "10.0.0.41": {"name": "older", "seen": now - 50},
                 "10.0.0.42": {"name": "expired", "seen": now - ml.IP_TTL_S - 5}, "10.0.0.43": {"name": "kept", "seen": now}})
ml.by_mac["aa:bb:cc:00:00:40"] = {"name": "stored", "seen": now - 100}
ml.by_mac["aa:bb:cc:00:00:41"] = {"name": "stored2", "seen": now}
macs.update({"10.0.0.40": "aa:bb:cc:00:00:40", "10.0.0.41": "aa:bb:cc:00:00:41"})
ml._dirty = False
ml._housekeeping()
assert ml.by_mac["aa:bb:cc:00:00:40"]["name"] == "new", "the newer card replaces the stored one"
assert ml.by_mac["aa:bb:cc:00:00:41"]["name"] == "stored2", "an older card does not replace a newer one"
assert set(ml.by_ip) == {"10.0.0.43"} and ml._dirty is True

# start-up: the MAC of an IP comes from the ARP view of the state; without zeroconf only the memory remains
state = SimpleNamespace(_view=SimpleNamespace(cache=(0, {"10.0.0.50": {"mac": "AA:BB:CC:00:00:50"}})))
started = []


async def fake_listen():
    started.append(1)


async def run():
    ml._listen = fake_listen
    ml._task = None
    sys.modules["zeroconf"] = None            # import fails
    ml.start(state)
    assert ml._task is None and ml._mac_for_ip("10.0.0.50") == "aa:bb:cc:00:00:50" and ml._mac_for_ip("10.0.0.51") is None
    sys.modules["zeroconf"] = SimpleNamespace()
    ml.start(state)
    await asyncio.sleep(0.01)
    assert started == [1]
    await ml.stop()
    await ml.stop()                            # a second stop is harmless


asyncio.new_event_loop().run_until_complete(run())
print("TUTTO OK")
