"""Characterization of the Bonjour (mDNS) memory with an announcement from an address of another network (reflected by a router between VLANs), before the work on more
networks: today it is already kept by address - the MAC of a device behind a router is never in the ARP table - and a card with that address finds the name even with a MAC
the memory never saw; once the MAC is known for an address the announcement goes under the MAC. The work on more networks relies on this (passive listening only, no
unicast question across the router). Documentation and private placeholder addresses.
    python tests/check_mdns_foreign_address.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_listener as m  # noqa: E402

LOCAL_ARP = {"10.0.0.20": "aa:bb:cc:00:00:14"}    # only the direct network is in the ARP table
m._mac_for_ip = lambda ip: LOCAL_ARP.get(ip)
m._at_several_addresses = lambda mac: False
m._lent_counts = None
m.by_mac.clear()
m.by_ip.clear()

# 1) an announcement from another network: kept by address, never under a MAC
m.record("10.0.20.30", "_http._tcp.local.", "iot-camera", "")
assert set(m.by_ip) == {"10.0.20.30"} and m.by_mac == {}, (m.by_ip, m.by_mac)
card = m.by_ip["10.0.20.30"]
assert card["name"] == "iot-camera" and card["ip"] == "10.0.20.30" and card["services"] == ["_http._tcp.local."], card

# 2) an announcement from the direct network: under its MAC
m.record("10.0.0.20", "_hap._tcp.local.", "main-lamp", "")
assert set(m.by_mac) == {"aa:bb:cc:00:00:14"} and set(m.by_ip) == {"10.0.20.30"}, (m.by_mac, m.by_ip)

# 3) the lookup: a card with the address of the other network gets the name whatever its MAC (none, or one never seen)
assert m.lookup(None, "10.0.20.30")["name"] == "iot-camera"
assert m.lookup("02:00:5e:00:00:99", "10.0.20.30")["name"] == "iot-camera"
assert m.lookup("AA-BB-CC-00-00-14", "10.0.0.20")["name"] == "main-lamp", "the MAC is normalized"
assert m.lookup(None, "10.0.20.31") is None

# 4) by address only while recent (an address can change owner)
m.by_ip["10.0.20.30"]["seen"] = 0
assert m.lookup(None, "10.0.20.30") is None

# 5) once the MAC of that address is known, a new announcement moves the card under the MAC
LOCAL_ARP["10.0.20.30"] = "aa:bb:cc:00:00:1e"
m.record("10.0.20.30", "_http._tcp.local.", "iot-camera", "")
assert "10.0.20.30" not in m.by_ip and m.by_mac["aa:bb:cc:00:00:1e"]["name"] == "iot-camera", (m.by_ip, m.by_mac)

# 6) a value that is not an IPv4 address is ignored
m.record("fe80::1", "_http._tcp.local.", "x", "")
m.record("10.0.20.300", "_http._tcp.local.", "x", "")
assert "fe80::1" not in m.by_ip and "10.0.20.300" not in m.by_ip

print("check_mdns_foreign_address: ok")
