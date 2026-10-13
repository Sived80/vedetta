"""Phase 3 of the MAC layer: are two MACs the same device? The linker on scenarios taken from real cases: a phone that switches between its factory
MAC and a private MAC (same DHCP name, vendor class and parameter list, one starts where the other stops), two identical phones active together,
a generic name shared by many devices, a handover with no other proof (a replaced device), and missing data (omitted, never counted against)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macidentity as mi  # noqa: E402

H = 3600.0
PIXEL = {"hostname": "Pixel-7", "fingerprint": "android-dhcp-17|1,3,6,15,26,28,51,58,59,43,114,108"}
IPHONE = {"hostname": "iPhone", "fingerprint": "|1,121,3,6,15,108,114,119,162,252"}


def mac(ip, sessions, **fields):
    s = [(a * H, b * H, (ip,)) for a, b in sessions]
    return {"first": s[0][0], "last": s[-1][1], "ips": {ip}, "sessions": s, **fields}


def network(extra=None):
    """A small home: a phone (two MACs), a few iPhones with the same generic name and list, a TV and a plug without DHCP data."""
    f = {
        "FAC": mac("10.0.0.108", [(0, 3.7), (4.0, 5.0)], **PIXEL),           # factory MAC, away while the private one is on
        "PRI": mac("10.0.0.116", [(3.7, 4.0)], **PIXEL),                       # private MAC: starts where the factory one stops
        "TV": mac("10.0.0.50", [(0, 5)]), "PLUG": mac("10.0.0.51", [(0, 5)]),
    }
    for i in range(4):
        f[f"IP{i}"] = mac(f"10.0.0.{60 + i}", [(0, 5)], **IPHONE)
    f.update(extra or {})
    return f


def zone(feats, a, b):
    return next(p for p in mi.link(feats) if {p["a"], p["b"]} == {a, b})


# 1) the phone: three independent proofs and a handover -> same device
p = zone(network(), "FAC", "PRI")
assert p["zone"] == "same" and p["score"] >= mi.SAME_AT, p
assert {w.split()[0] for w in p["why"]} >= {"hostname", "fingerprint"} and any("inizia" in w for w in p["why"])

# 2) a generic name and a parameter list shared by four iPhones weigh little: they are NOT merged, and the weights are small
for i in range(4):
    for j in range(i + 1, 4):
        q = zone(network(), f"IP{i}", f"IP{j}")
        assert q["zone"] != "same" and q["score"] < 0, q
u = mi.estimate_u(network())
assert u["hostname"]["iPhone"] > 0.2 and u["hostname"]["Pixel-7"] < 0.15 and u["fingerprint"][IPHONE["fingerprint"]] > 0.2, u

# 3) two identical phones (same name, class and list) active together at different addresses: not the same device
twin = network({"TWIN": mac("10.0.0.120", [(0, 5)], **PIXEL)})
assert zone(twin, "FAC", "TWIN")["zone"] == "different" and any("insieme" in w for w in zone(twin, "FAC", "TWIN")["why"])

# 4) a handover with NO other proof (a device replaced by another) must not merge: possible at most
rep = network({"OLD": mac("10.0.0.70", [(0, 2)]), "NEW": mac("10.0.0.70", [(2.0, 5)])})
r = zone(rep, "OLD", "NEW")
assert r["zone"] != "same" and r["score"] > mi.PRIOR_LOGODDS, r

# 4b) in a big network a handover is rare, so uncapped it would weigh a lot: the cap keeps it from ever merging by itself
big = network({"OLD": mac("10.0.1.1", [(0, 2)]), "NEW": mac("10.0.1.1", [(2.0, 5)])})
big.update({f"F{i}": mac(f"10.0.2.{i}", [(0, 5)]) for i in range(80)})
rb = zone(big, "OLD", "NEW")
assert rb["zone"] != "same" and rb["score"] <= mi.PRIOR_LOGODDS + mi.HANDOFF_MAX_WEIGHT + 0.01, rb

# 5) a different name on both sides is evidence against; a missing field is simply omitted
diff = network({"OTHER": mac("10.0.0.130", [(3.7, 5)], hostname="Galaxy", fingerprint=PIXEL["fingerprint"])})
assert zone(diff, "PRI", "OTHER")["zone"] == "different" and any("hostname diverso" in w for w in zone(diff, "PRI", "OTHER")["why"])
tvplug = zone(network(), "TV", "PLUG")
assert tvplug["zone"] == "different" and tvplug["why"] == ["attivi insieme su indirizzi diversi (-4.0)"], tvplug     # two devices at the same time
bare = zone(network({"E": mac("10.0.0.160", [(0, 1)]), "F": mac("10.0.0.161", [(3.0, 4)])}), "E", "F")
assert bare["why"] == [] and bare["zone"] == "unrelated", bare            # nothing in common and far apart: no evidence either way, not "different"

# 5b) two DIFFERENT devices of the same OS family (same fingerprint, no name) that happen to hand over: one fingerprint is not enough to merge
fam = network({"X": mac("10.0.0.150", [(0, 2)], fingerprint=PIXEL["fingerprint"]), "Y": mac("10.0.0.151", [(2.0, 5)], fingerprint=PIXEL["fingerprint"])})
fz = zone(fam, "X", "Y")
assert fz["zone"] != "same" and sum(1 for w in fz["why"] if w.startswith("fingerprint")) == 1, fz

# 6) a client identifier, when recorded, is the strongest proof and is used like any field
cid = network({"A": mac("10.0.0.140", [(0, 2)], client_id="01:aa:bb"), "B": mac("10.0.0.141", [(2.0, 5)], client_id="01:aa:bb")})
assert zone(cid, "A", "B")["zone"] == "same", zone(cid, "A", "B")

# 7) results are complete and ordered: every pair once, best first
res = mi.link(network())
assert len(res) == 8 * 7 // 2 and res == sorted(res, key=lambda r: -r["score"]) and res[0]["zone"] == "same"
assert mi.link({}) == [] and mi.link({"X": {}}) == []

# ------------------------------------------------------------------ review fixes
import random  # noqa: E402
import time  # noqa: E402


def crowd(n, distinct=False, **extra):
    """n unrelated devices (always on) around the pair under test: a big network. With distinct=True each has a fingerprint of its own, so a value
    shared by just two of them looks very rare (the case that used to weigh +10)."""
    f = {f"Z{i}": mac(f"10.9.{i // 200}.{i % 200}", [(0, 5)], **({"fingerprint": f"|z{i}", "hostname": f"z{i}"} if distinct else {})) for i in range(n)}
    f.update(extra)
    return f


# 8) two DIFFERENT devices of the same rare model (same fingerprint, no name), one switching off as the other switches on, in a big network:
#    one rare value used to weigh +10 and merged them; with the floor and the need for strong evidence they stay apart
rare = {"fingerprint": "|9,8,7,6,5,4,3,2,1"}
big = crowd(60, distinct=True, X=mac("10.0.0.150", [(0, 2)], **rare), Y=mac("10.0.0.151", [(2.0, 5)], **rare))
r8 = zone(big, "X", "Y")
assert r8["zone"] == "possible" and r8["score"] < mi.SAME_AT, r8
u_big = mi.estimate_u(big)
assert u_big["fingerprint"][rare["fingerprint"]] == mi.FIELD_U_FLOOR["fingerprint"], "a rare value never weighs more than its floor"
assert mi.estimate_u(crowd(60, distinct=True, N1=mac("10.0.0.1", [(0, 5)], hostname="solo"), N2=mac("10.0.0.2", [(0, 5)], hostname="solo")))["hostname"]["solo"] == mi.FIELD_U_FLOOR["hostname"]

# 9) two devices with the same name AND the same fingerprint active together at different addresses (two Raspberry Pis): never the same device
twin2 = crowd(40, distinct=True, P1=mac("10.0.0.170", [(0, 5)], hostname="raspberrypi", fingerprint="|1,3,6,15"), P2=mac("10.0.0.171", [(0, 5)], hostname="raspberrypi", fingerprint="|1,3,6,15"))
r9 = zone(twin2, "P1", "P2")
assert r9["zone"] != "same" and any("insieme" in w for w in r9["why"]), r9

# 10) ONE host with two cards: the same client identifier at two addresses at once is not evidence against, it is the proof of a dual-homed host
dual = crowd(10, C1=mac("10.0.0.180", [(0, 5)], client_id="ff:aa:01"), C2=mac("10.0.0.181", [(0, 5)], client_id="ff:aa:01"))
r10 = zone(dual, "C1", "C2")
assert r10["zone"] == "same" and any("due schede" in w for w in r10["why"]) and not any("insieme su indirizzi diversi" in w for w in r10["why"]), r10

# 11) "same" needs strong evidence: with the threshold lowered to nothing, ONE agreeing field still cannot make two MACs the same device,
#     while two independent agreeing fields can
old_same = mi.SAME_AT
mi.SAME_AT = -100.0
one = crowd(5, S1=mac("10.0.0.190", [(0, 2)], fingerprint="|1,2,3"), S2=mac("10.0.0.191", [(2.0, 5)], fingerprint="|1,2,3"))
two = crowd(5, S1=mac("10.0.0.190", [(0, 2)], fingerprint="|1,2,3", hostname="alpha"), S2=mac("10.0.0.191", [(2.0, 5)], fingerprint="|1,2,3", hostname="alpha"))
assert zone(one, "S1", "S2")["zone"] == "possible" and zone(two, "S1", "S2")["zone"] == "same"
mi.SAME_AT = old_same

# 12) the fast relation (two pointers over sorted sessions) gives exactly what the plain definition gives, on random sessions
rng = random.Random(5)
for _ in range(400):
    def rand_sessions(ip):
        out, tt = [], rng.random() * 10
        for _k in range(rng.randrange(1, 6)):
            s = tt + rng.random() * 5
            e = s + rng.choice((0.0, rng.random() * 4))
            out.append((s, e, (ip + str(rng.randrange(2)),)))
            tt = e
        return out
    sa, sb = rand_sessions("a"), rand_sessions("a")
    together = any(min(e0, e1) > max(s0, s1) and not (set(i0) & set(i1)) for s0, e0, i0 in sa for s1, e1, i1 in sb)
    overlap = any(min(e0, e1) > max(s0, s1) for s0, e0, _ in sa for s1, e1, _ in sb)
    gaps = [max(s0, s1) - min(e0, e1) for s0, e0, _ in sa for s1, e1, _ in sb if not min(e0, e1) > max(s0, s1)]
    want = (together, None if overlap else (min(gaps) if gaps else None))
    got = mi._relation(sorted(sa), sorted(sb))
    assert got[0] == want[0] and (got[1] == want[1] or (got[1] is not None and want[1] is not None and abs(got[1] - want[1]) < 1e-9)), (sa, sb, got, want)
assert mi._relation([(0, 10, ("a",))], [(10, 20, ("b",))]) == (False, 0), "touching sessions: no overlap, no gap"

# 13) it is fast enough to run in the export: 250 MACs with 10 sessions each
rng = random.Random(1)
farm = {}
for i in range(250):
    ss, tt = [], 0.0
    for _k in range(10):
        s = tt + rng.random() * 5000
        e = s + rng.random() * 3000
        ss.append((s, e, (f"10.0.0.{i}",)))
        tt = e
    farm[f"AA:{i // 256:02X}:{i % 256:02X}"] = {"first": ss[0][0], "last": ss[-1][1], "ips": {f"10.0.0.{i}"}, "sessions": ss,
                                               "hostname": rng.choice(["a", "b", "c", None]), "fingerprint": rng.choice(["x", "y", None])}
t0 = time.time()
assert len(mi.link(farm)) == 250 * 249 // 2
assert time.time() - t0 < 4.0, "the linker is too slow for the export"
# 14) the order the sessions come in must not matter (the database gives them sorted, a caller may not)
shuffled = network()
shuffled["FAC"] = dict(shuffled["FAC"], sessions=list(reversed(shuffled["FAC"]["sessions"])))
assert zone(shuffled, "FAC", "PRI") == zone(network(), "FAC", "PRI")
# 14b) with the sessions in the wrong order a naive scan would miss an overlap: the result must be the same either way
two_a = {"A1": mac("10.0.0.201", [(0, 1), (10, 11)]), "A2": mac("10.0.0.202", [(0.5, 0.9)])}
rev = {"A1": dict(two_a["A1"], sessions=list(reversed(two_a["A1"]["sessions"]))), "A2": two_a["A2"]}
assert mi.link(rev)[0]["why"] == mi.link(two_a)[0]["why"] and any("insieme" in w for w in mi.link(rev)[0]["why"])
print("TUTTO OK")
