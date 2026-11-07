"""The check of a network written by the person (networks/model.py): every value that comes from outside gives a Network or is refused with a known code, never another
exception and never a silent fix.
1) the known cases and refusals; 2) the limit on the number of networks; 3) 4000 hostile values with a fixed seed; 4) 3000 "nearly valid" networks, one field broken at a
time, so that every refusal code is reached (the truth - which code - is decided by the generator, not by the code under test); 5) what an accepted Network keeps.
Invented private addresses only (10.x and 192.168.50-99.x).
    python tests/check_networks_model.py"""
import ipaddress
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import model as m  # noqa: E402

MAIN = m.Network("main", ipaddress.ip_network("192.168.50.0/24"), frozenset({"direct"}), "full", "confirmed")
BASE = {"id": "iot", "cidr": "192.168.60.0/24", "via": ["routed"], "touch": "presence"}


def code(candidate, existing=(MAIN,)):
    try:
        m.validate(candidate, existing)
    except m.Rejected as exc:
        return exc.code
    return None


# 1) known cases
assert code(BASE) is None
net = m.validate({**BASE, "exclude": ["192.168.60.200-192.168.60.220", "192.168.60.7"]}, [MAIN])
assert net.id == "iot" and str(net.cidr) == "192.168.60.0/24" and net.via == frozenset({"routed"}) and net.touch == "presence" and net.state == "proposed", net
assert net.holds(ipaddress.ip_address("192.168.60.5")) and not net.holds(ipaddress.ip_address("192.168.60.210")) and not net.holds(ipaddress.ip_address("192.168.60.7"))
assert not net.holds(ipaddress.ip_address("192.168.61.5"))
KNOWN = {
    "public": ({**BASE, "cidr": "198.51.100.0/24"}, "E_PUBLIC"),
    "carrier-grade NAT is not private": ({**BASE, "cidr": "100.64.1.0/24"}, "E_PUBLIC"),
    "link local": ({**BASE, "cidr": "169.254.1.0/24"}, "E_PUBLIC"),
    "the Supervisor network": ({**BASE, "cidr": "172.30.32.0/23"}, "E_CONTAINER_NET"),
    "the Docker bridge": ({**BASE, "cidr": "172.17.5.0/24"}, "E_CONTAINER_NET"),
    "overlaps the main one": ({**BASE, "cidr": "192.168.50.0/25"}, "E_OVERLAP"),
    "contains the main one": ({**BASE, "cidr": "192.168.48.0/22"}, "E_OVERLAP"),
    "too wide behind a router": ({**BASE, "cidr": "10.0.0.0/21"}, "E_TOO_WIDE"),
    "too wide seen by a controller": ({**BASE, "cidr": "10.0.0.0/23", "via": ["controller"]}, "E_TOO_WIDE"),
    "host bits are refused, not fixed": ({**BASE, "cidr": "192.168.60.5/24"}, "E_CIDR"),
    "an option smuggled in": ({**BASE, "cidr": "192.168.60.0/24 --x"}, "E_CIDR"),
    "spaces": ({**BASE, "cidr": " 192.168.60.0/24"}, "E_CIDR"),
    "a prefix with a leading zero (read as /24, never rewritten)": ({**BASE, "cidr": "192.168.60.0/024"}, "E_CIDR"),
    "IPv6": ({**BASE, "cidr": "fd00::/64"}, "E_NOT_IPV4"),
    "a single address": ({**BASE, "cidr": "192.168.60.7/32"}, "E_TOO_NARROW"),
    "a whole search needs the own interface": ({**BASE, "touch": "full"}, "E_TOUCH_NEEDS_DIRECT"),
    "same id": ({**BASE, "id": "main", "cidr": "192.168.61.0/24"}, "E_DUP_ID"),
    "excluded outside": ({**BASE, "exclude": ["192.168.61.5"]}, "E_BAD_EXCLUDE"),
    "excluded reversed": ({**BASE, "exclude": ["192.168.60.9-192.168.60.3"]}, "E_BAD_EXCLUDE"),
    "excluded not text": ({**BASE, "exclude": [7]}, "E_BAD_EXCLUDE"),
    "via as text": ({**BASE, "via": "routed"}, "E_BAD_VIA"),
    "no via": ({**BASE, "via": []}, "E_BAD_VIA"),
    "not a dictionary": (["192.168.60.0/24"], "E_SHAPE"),
}
for name, (cand, expected) in KNOWN.items():
    assert code(cand) == expected, (name, code(cand), expected)
assert code({**BASE, "cidr": "10.1.0.0/16", "via": ["direct"]}) is None, "a wide network on the own interface is fine"
assert code({**BASE, "cidr": "10.1.0.0/22"}) is None and code({**BASE, "cidr": "192.168.60.0/30"}) is None, "the limits themselves are allowed"
assert code(BASE, existing=()) is None, "empty world: no network yet"

# 2) at most MAX_NETWORKS, the main one counted
nets = [MAIN]
for i in range(1, m.MAX_NETWORKS):
    nets.append(m.validate({"id": "n%d" % i, "cidr": "192.168.%d.0/24" % (60 + i), "via": ["routed"]}, nets))
assert len(nets) == m.MAX_NETWORKS
assert code({"id": "last", "cidr": "192.168.90.0/24", "via": ["routed"]}, nets) == "E_TOO_MANY"

rng = random.Random(20261107)


def check_accepted(cand, got):
    """What an accepted network must be: private, outside the containers, apart from the main one, its network exactly as written."""
    assert any(got.cidr.subnet_of(p) for p in m.PRIVATE), got
    assert not any(got.cidr.overlaps(c) for c in m.CONTAINER), got
    assert not got.cidr.overlaps(MAIN.cidr), got
    assert str(got.cidr) == cand["cidr"], (got.cidr, cand["cidr"])


# 3) hostile values: a Network or a known code, nothing else
ALPHA = "0123456789./:-abcdefxXG \t\n\x00;&|$`'\"*%é‮"


def hostile():
    if rng.randrange(6) == 0:
        return rng.choice([None, 5, 3.4, [], "x", b"1", True])
    junk = "".join(rng.choice(ALPHA) for _ in range(rng.randrange(0, 24)))
    pick = rng.choice
    quad = "%d.%d.%d.%d/%d" % (tuple(rng.randrange(256) for _ in range(4)) + (rng.randrange(33),))
    return {"id": pick(["a", junk, "x" * 40, "ok-1", None, 7]), "cidr": pick(["192.168.%d.0/24" % rng.randrange(256), junk, quad, rng.randrange(99), None]),
            "via": pick([["routed"], ["direct"], ["x"], [], "routed", None, ["routed", "snmp"], [junk]]), "touch": pick(["presence", "ports", "full", junk, None]),
            "state": pick(["proposed", "confirmed", "paused", junk]), "exclude": pick([[], [junk], ["192.168.60.1"], "x", None, [junk] * 40])}


accepted = 0
for _ in range(4000):
    cand = hostile()
    try:
        got = m.validate(cand, [MAIN])
    except m.Rejected as exc:
        assert exc.code in m.CODES, exc.code
        continue
    accepted += 1
    check_accepted(cand, got)
assert accepted > 0, "the generator never makes a valid network"


# 4) nearly valid: one field broken at a time, the generator knows which code must come
def valid():
    third = rng.randrange(60, 100)
    prefix = rng.choice([22, 23, 24, 26, 30])
    cidr = str(ipaddress.ip_network("192.168.%d.0/%d" % (third - third % 4 if prefix == 22 else third - third % 2 if prefix == 23 else third, prefix), strict=False))
    return {"id": rng.choice(["iot", "media", "cams-2", "x_y"]), "cidr": cidr, "via": rng.choice([["routed"], ["routed", "snmp"], ["direct"]]),
            "touch": rng.choice(["presence", "ports"]), "state": rng.choice(list(m.STATES)), "exclude": []}


BREAKS = [
    (lambda c: c.update(cidr=c["cidr"].replace("/", "/0")), "E_CIDR"),
    (lambda c: c.update(cidr="fd00:%x::/64" % rng.randrange(1 << 16)), "E_NOT_IPV4"),
    (lambda c: c.update(via=[rng.choice(["wifi", "", "ROUTED"])]), "E_BAD_VIA"),
    (lambda c: c.update(touch=rng.choice(["all", "", "Full"])), "E_BAD_TOUCH"),
    (lambda c: c.update(state=rng.choice(["on", "", "Confirmed"])), "E_BAD_STATE"),
    (lambda c: c.update(id=rng.choice(["", "a b", "x" * 17, "nét", "a/b"])), "E_BAD_ID"),
    (lambda c: c.update(cidr="203.0.113.0/24"), "E_PUBLIC"),
    (lambda c: c.update(cidr="172.30.32.0/24"), "E_CONTAINER_NET"),
    (lambda c: c.update(cidr="10.%d.0.0/16" % rng.randrange(256), via=["routed"]), "E_TOO_WIDE"),
    (lambda c: c.update(cidr="192.168.60.4/31"), "E_TOO_NARROW"),
    (lambda c: c.update(touch="full", via=["routed"]), "E_TOUCH_NEEDS_DIRECT"),
    (lambda c: c.update(id="main"), "E_DUP_ID"),
    (lambda c: c.update(cidr="192.168.50.%d/30" % (4 * rng.randrange(64))), "E_OVERLAP"),
    (lambda c: c.update(exclude=["192.168.%d.1" % rng.randrange(100, 200)]), "E_BAD_EXCLUDE"),
    (lambda c: c.update(exclude=["192.168.60.1"] * (m.MAX_EXCLUDE + 1)), "E_BAD_EXCLUDE"),
]
reached = set()
for _ in range(3000):
    cand = valid()
    assert code(cand) is None, cand
    breaker, expected = rng.choice(BREAKS)
    breaker(cand)
    got = code(cand)
    assert got == expected, (cand, got, expected)
    reached.add(got)
assert reached == set(m.CODES) - {"E_SHAPE", "E_TOO_MANY"}, set(m.CODES) - reached     # those two are proved in 1) and 2)

# 5) an accepted network is frozen and keeps no reference to the request
cand = {**BASE, "via": ["routed"]}
got = m.validate(cand, [MAIN])
cand["via"].append("direct")
assert got.via == frozenset({"routed"})
try:
    got.touch = "full"
except Exception:
    pass
else:
    raise AssertionError("a Network must not change after the check")

print("check_networks_model: ok (%d hostile values accepted)" % accepted)
