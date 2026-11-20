"""1.0 step P11 (decisions 1A, 2A): routedinv.merge, the inventory by address of a network behind the router. Pure; invented private addresses.
- the first sweep of a network is the starting point: every address that answered is listed as new, nothing is alerted; a sweep where
  nothing answered is not a starting point (it waits, like an empty ARP on the home network);
- afterwards an address never seen is new and alerted once; seen again it is not alerted again, and its first sight stays;
- never a MAC made up: the MAC comes only from the trackers of Home Assistant (by address), and is kept when they stop saying it;
- a card is never new: an address of a card without a link, a configured MAC (a linked card, an adopted device of Home Assistant); a new
  row that became a card is known at the next sweep;
- the rule by MAC: a MAC already seen (known on the home network, at another address) is not new; one still "new" stays new without a second
  alert; a different MAC at an address already seen is another device;
- the ignored ones (blocked by MAC, address or name) are not written at all; the names come from Home Assistant, else from mDNS;
- an address out of the network (or in an excluded range) is never written.
    python tests/check_routedinv.py"""
import ipaddress
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import routedinv  # noqa: E402
from app.networks.model import Network  # noqa: E402

NET = Network("vlan60", ipaddress.ip_network("192.168.60.0/24"), frozenset({"routed"}), "presence", "confirmed",
              exclude=((int(ipaddress.ip_address("192.168.60.200")), int(ipaddress.ip_address("192.168.60.210"))),))
MAC_A, MAC_B, MAC_C = "02:00:5E:60:00:0A", "02:00:5E:60:00:0B", "02:00:5E:60:00:0C"


def ip(i):
    return "192.168.60.%d" % i


def by_ip(rows):
    return {r["ip"]: r for r in rows}


# 1) the first sweep: the starting point
out = routedinv.merge(NET, [ip(5), ip(6), ip(5)], [], 100.0, trackers={ip(6): {"mac": MAC_A, "host": "printer", "name": None}})
assert out.baseline and out.fresh == [], out
rows = by_ip(out.rows)
assert sorted(rows) == [ip(5), ip(6)], "each address once"
assert all(r["status"] == "new" and r["first_seen"] == r["last_seen"] == 100.0 and r["network"] == "vlan60" for r in rows.values()), rows
assert rows[ip(5)]["mac"] is None and rows[ip(6)]["mac"] == MAC_A and rows[ip(6)]["host"] == "printer", rows
assert out.with_mac == 1, out
empty = routedinv.merge(NET, [], [], 100.0)
assert empty.baseline and empty.rows == [] and empty.fresh == [], "nothing answered: no starting point yet"

# 2) afterwards: a never-seen address is new, alerted once
prev = out.rows
out2 = routedinv.merge(NET, [ip(5), ip(7)], prev, 200.0, names={ip(7): "speaker"})
assert not out2.baseline, out2
assert [(f["ip"], f["mac"], f["hostname"], f["first_seen"], f["network"]) for f in out2.fresh] == [(ip(7), None, "speaker", 200.0, "vlan60")], out2.fresh
rows2 = by_ip(out2.rows)
assert rows2[ip(7)]["status"] == "new" and rows2[ip(5)]["status"] == "new" and rows2[ip(5)]["first_seen"] == 100.0 and rows2[ip(5)]["last_seen"] == 200.0, rows2
assert ip(6) not in rows2, "an address that did not answer is not written: its last sight stays"
prev3 = [r for r in prev if r["ip"] != ip(5)] + out2.rows
out3 = routedinv.merge(NET, [ip(7)], prev3, 300.0)
assert out3.fresh == [] and by_ip(out3.rows)[ip(7)]["status"] == "new" and by_ip(out3.rows)[ip(7)]["first_seen"] == 200.0, "seen again: still new, never a second alert"
assert by_ip(out3.rows)[ip(7)]["host"] == "speaker", "a name already heard stays"

# 3) never a MAC made up; one said once is kept
out4 = routedinv.merge(NET, [ip(6)], prev, 400.0)
assert by_ip(out4.rows)[ip(6)]["mac"] == MAC_A and out4.with_mac == 0, "the MAC from Home Assistant stays when it is no longer said (not counted as said now)"
assert all(r["mac"] is None for r in routedinv.merge(NET, [ip(8), ip(9)], prev, 400.0).rows), "no tracker: no MAC"

# 4) a card is never new
known = routedinv.Known(card_ips=frozenset({ip(8)}), card_macs=frozenset({MAC_B}))
out5 = routedinv.merge(NET, [ip(8), ip(9)], prev, 500.0, trackers={ip(9): {"mac": MAC_B, "host": None, "name": "tv"}}, known=known)
assert out5.fresh == [] and all(r["status"] == "known" for r in out5.rows), out5
assert by_ip(out5.rows)[ip(9)]["host"] == "tv", "the name Home Assistant shows when there is no host name"
became = routedinv.merge(NET, [ip(7)], prev3, 600.0, known=routedinv.Known(card_ips=frozenset({ip(7)})))
assert by_ip(became.rows)[ip(7)]["status"] == "known" and became.fresh == [], "a new address that is a card now becomes known"

# 5) the rule by MAC
seen = routedinv.Known(macs={MAC_B: "known", MAC_C: "new"})
out6 = routedinv.merge(NET, [ip(20), ip(21)], prev, 700.0, trackers={ip(20): {"mac": MAC_B, "host": None, "name": None}, ip(21): {"mac": MAC_C, "host": None, "name": None}}, known=seen)
assert out6.fresh == [], "a MAC already seen is not alerted again"
assert by_ip(out6.rows)[ip(20)]["status"] == "known" and by_ip(out6.rows)[ip(21)]["status"] == "new", "a MAC still new stays in the list, without a second alert"
out7 = routedinv.merge(NET, [ip(6)], prev, 800.0, trackers={ip(6): {"mac": MAC_C, "host": None, "name": None}})
assert [f["mac"] for f in out7.fresh] == [MAC_C] and by_ip(out7.rows)[ip(6)]["first_seen"] == 800.0, "another MAC at an address already seen: another device"

# 6) the ignored ones and the addresses out of the network
blocked = lambda mac, address, name: address == ip(30) or mac == MAC_B or name == "guest"  # noqa: E731
out8 = routedinv.merge(NET, [ip(30), ip(31), ip(32), ip(33)], prev, 900.0, trackers={ip(31): {"mac": MAC_B, "host": None, "name": None}}, names={ip(32): "guest"}, blocked=blocked)
assert [r["ip"] for r in out8.rows] == [ip(33)] and [f["ip"] for f in out8.fresh] == [ip(33)], out8
out9 = routedinv.merge(NET, ["192.168.61.5", ip(205), "not an address"], prev, 900.0)
assert out9.rows == [] and out9.fresh == [], "out of the network, in an excluded range, not an address: never written"
assert routedinv.merge(NET, [ip(5)], [{**prev[0], "ip": "192.168.61.5"}], 900.0).baseline, "a row of another range does not count as the starting point"
print("check_routedinv: ok")
