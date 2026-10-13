"""Phase 2 of the MAC layer: the classification of MACs and conflicts on a library of fake networks (no brand, no device: only behaviours).
Each scenario builds the rows of ip_mac the way the layer stores them. Thresholds are in macclassify.py and get tuned with real data."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macclassify as mc  # noqa: E402


def row(ip, mac, source="arp", first=0.0, last=3600.0, n=50):
    return {"ip": ip, "mac": mac, "source": source, "first_seen": first, "last_seen": last, "seen_count": n}


def kinds(rows):
    r = mc.classify(rows)
    return {m: v["kind"] for m, v in r["macs"].items()}, r


R, A, B, C = "00:11:22:00:00:01", "00:11:22:00:00:0A", "00:11:22:00:00:0B", "00:11:22:00:00:0C"

# 1) a quiet home: every MAC at one address is normal; a random (private) MAC is recognised as such
k, r = kinds([row("10.0.0.2", R), row("10.0.0.3", A), row("10.0.0.4", "4E:3A:FD:00:00:A5")])
assert k == {R: "normal", A: "normal", "4E:3A:FD:00:00:A5": "private"} and r["conflicts"] == []

# 2) a repeater lends its MAC to three clients (ARP shows the repeater MAC at three addresses); DHCP shows the real client MACs
rows = [row(f"10.0.0.{i}", R) for i in (20, 21, 22)] + [row("10.0.0.20", A, "dhcp"), row("10.0.0.21", B, "dhcp"), row("10.0.0.22", C, "dhcp")]
k, r = kinds(rows)
assert k[R] == "lender" and r["macs"][R]["behind"] == [A, B, C] and r["conflicts"] == [], "the lender explains the three addresses"
assert r["clients"] == {"10.0.0.20": A, "10.0.0.21": B, "10.0.0.22": C}, "DHCP names who really is at each address"
assert k[A] == k[B] == k[C] == "normal"

# 3) only two addresses and no proof: a host with two addresses, not a lender (decision 1); with DHCP proof of a client behind it, a lender
k, _ = kinds([row("10.0.0.30", R), row("10.0.0.31", R)])
assert k[R] == "multi_address"
k, r = kinds([row("10.0.0.30", R), row("10.0.0.31", R), row("10.0.0.30", A, "dhcp")])
assert k[R] == "lender" and r["macs"][R]["behind"] == [A]

# 4) a real conflict (two devices on one address, interleaved for hours): both MACs are conflict, one entry for the pair
rows = [row("10.0.1.5", A, first=0, last=7200, n=120), row("10.0.1.5", B, first=100, last=7000, n=115)]
k, r = kinds(rows)
assert k == {A: "conflict", B: "conflict"} and r["conflicts"] == [{"ip": "10.0.1.5", "macs": [A, B]}]

# 5) a device replaced (the new one takes the address after the old one left): no overlap, no conflict
k, r = kinds([row("10.0.1.6", A, first=0, last=1000), row("10.0.1.6", B, first=1500, last=3600)])
assert k == {A: "normal", B: "normal"} and r["conflicts"] == []
# ... and a brief overlap or a MAC seen a couple of times is noise, not a conflict
k, r = kinds([row("10.0.1.7", A, first=0, last=1000), row("10.0.1.7", B, first=990, last=3000)])
assert r["conflicts"] == []
k, r = kinds([row("10.0.1.8", A, first=0, last=3600), row("10.0.1.8", B, first=0, last=3600, n=2)])
assert r["conflicts"] == []

# 6) a lender's bursts on a client address are not a conflict (the lender explains the second MAC)
rows = [row(f"10.0.0.{i}", R) for i in (20, 21, 22)] + [row("10.0.0.20", A, first=0, last=3600, n=80), row("10.0.0.20", A, "dhcp")]
k, r = kinds(rows)
assert k[R] == "lender" and r["conflicts"] == [], "the lender and the client at the same address are not a conflict"

# 7) a mesh: a phone roams between two nodes keeping its address; the nodes have several MACs (one per radio): nothing is a lender or a conflict
rows = [row("10.0.0.50", A, last=1800), row("10.0.0.50", A, "dhcp", last=3600), row("10.0.0.2", R), row("10.0.0.2", "00:11:22:00:00:02", "mdns")]
k, r = kinds(rows)
assert k[A] == "normal" and k[R] == "normal" and r["conflicts"] == [], k

# 8) a PC with two network cards on the same segment: two MACs, two addresses, same DHCP name: each is normal (the link to one host is a later phase)
k, r = kinds([row("10.0.0.60", A), row("10.0.0.61", B), row("10.0.0.60", A, "dhcp"), row("10.0.0.61", B, "dhcp")])
assert k == {A: "normal", B: "normal"} and r["conflicts"] == []

# 9) virtual router MACs of VRRP / HSRP are shared by design: never a lender, never a conflict, even on many addresses or against the real MACs
for virtual in ("00:00:5E:00:01:0A", "00:00:0C:07:AC:14", "00:00:0C:9F:F0:01"):
    rows = [row(f"10.0.2.{i}", virtual) for i in (1, 2, 3, 4)] + [row("10.0.2.1", A, n=90)]
    k, r = kinds(rows)
    assert k[virtual] == "virtual" and r["conflicts"] == [], virtual

# 10) mDNS-only rows never make a lender or a conflict (they are names, not proof of who answers ARP)
k, r = kinds([row(f"10.0.3.{i}", R, "mdns") for i in (1, 2, 3, 4)])
assert k[R] == "normal" and r["conflicts"] == []
assert mc.classify([]) == {"macs": {}, "conflicts": [], "possible_conflicts": [], "clients": {}}

# ---------------------------------------------------------------- phase 2b: sessions (when each MAC was really active) and flips (changes at an address)
D = 86400.0


def row2(ip, mac, first, last, source="arp", n=50):
    return row(ip, mac, source, first, last, n)


def sess(ip, mac, start, end, source="arp"):
    return {"ip": ip, "mac": mac, "source": source, "start": start, "end": end}


def flipset(ip, a, b, n, step=60.0, t0=0.0):
    return [{"ip": ip, "old": (a if i % 2 == 0 else b), "new": (b if i % 2 == 0 else a), "ts": t0 + i * step} for i in range(n)]


def kinds2(rows, sessions, flips=None):
    r = mc.classify(rows, sessions, flips)
    return {m: v["kind"] for m, v in r["macs"].items()}, r


# 11) a phone that gets a new address each time it comes back: three addresses over weeks but NEVER at once -> not a lender (it used to be one)
rows = [row2(f"10.0.5.{i}", A, first=i * 10 * D, last=i * 10 * D + 5 * D) for i in (1, 2, 3)]
ss = [sess(f"10.0.5.{i}", A, i * 10 * D, i * 10 * D + 5 * D) for i in (1, 2, 3)]
assert kinds(rows)[0][A] == "lender", "without sessions the old rule is kept"
k, r = kinds2(rows, ss)
assert k[A] == "normal" and r["macs"][A]["behind"] == []

# 12) a real lender: the three addresses are active together -> still a lender, with the clients that DHCP shows at the same time
rows = [row2(f"10.0.0.{i}", R, 0, 3600) for i in (20, 21, 22)] + [row2("10.0.0.20", A, 0, 3600, "dhcp"), row2("10.0.0.21", B, 0, 3600, "dhcp")]
ss = [sess(f"10.0.0.{i}", R, 0, 3600) for i in (20, 21, 22)] + [sess("10.0.0.20", A, 0, 3600, "dhcp"), sess("10.0.0.21", B, 0, 3600, "dhcp")]
k, r = kinds2(rows, ss)
assert k[R] == "lender" and r["macs"][R]["behind"] == [A, B]

# 13) a DHCP proof from a month earlier does not make a MAC with two addresses a lender (the proof must coincide in time with the ARP session)
rows = [row2("10.0.0.10", Q := "00:11:22:00:00:0D", 0, 3600, "dhcp"), row2("10.0.0.10", R, 40 * D, 41 * D), row2("10.0.0.20", R, 41 * D, 42 * D)]
ss = [sess("10.0.0.10", Q, 0, 3600, "dhcp"), sess("10.0.0.10", R, 40 * D, 41 * D), sess("10.0.0.20", R, 41 * D, 42 * D)]
k, _ = kinds2(rows, ss)
assert k[R] != "lender", k
k, _ = kinds(rows)
assert k[R] == "lender", "the coarse rule is fooled by the old proof: this is what the sessions fix"
# ... and two addresses at once WITH a DHCP proof at the same time is a lender
ss2 = [sess("10.0.0.10", Q, 40 * D, 41 * D, "dhcp"), sess("10.0.0.10", R, 40 * D, 41 * D), sess("10.0.0.20", R, 40 * D, 41 * D)]
rows2 = [row2("10.0.0.10", Q, 40 * D, 41 * D, "dhcp"), row2("10.0.0.10", R, 40 * D, 41 * D), row2("10.0.0.20", R, 40 * D, 41 * D)]
assert kinds2(rows2, ss2)[0][R] == "lender"

# 14) A, B, A on one address (a device handing its address to another and getting it back): two changes -> NOT a conflict although the spans overlap
rows = [row2("10.0.1.5", A, 0, 30 * D, n=200), row2("10.0.1.5", B, 10 * D, 20 * D, n=100)]
ss = [sess("10.0.1.5", A, 0, 10 * D), sess("10.0.1.5", B, 10 * D, 20 * D), sess("10.0.1.5", A, 20 * D, 30 * D)]
fl = [{"ip": "10.0.1.5", "old": A, "new": B, "ts": 10 * D}, {"ip": "10.0.1.5", "old": B, "new": A, "ts": 20 * D}]
assert kinds(rows)[1]["conflicts"], "the coarse rule calls it a conflict"
k, r = kinds2(rows, ss, fl)
assert r["conflicts"] == [] and k == {A: "normal", B: "normal"}

# 15) a real conflict: both sessions overlapping, continuous alternation every minute -> conflict
rows = [row2("10.0.1.6", A, 0, 7200, n=120), row2("10.0.1.6", B, 0, 7200, n=118)]
ss = [sess("10.0.1.6", A, 0, 7200), sess("10.0.1.6", B, 0, 7200)]
k, r = kinds2(rows, ss, flipset("10.0.1.6", A, B, 100))
assert k == {A: "conflict", B: "conflict"} and r["conflicts"] == [{"ip": "10.0.1.6", "macs": [A, B]}]

# 16) a repeater answering for a client in rare bursts (a few changes hours apart) -> not a conflict, and few changes are not a conflict either
fl = flipset("10.0.1.7", A, B, 8, step=3 * 3600.0)
k, r = kinds2([row2("10.0.1.7", A, 0, 40000, n=300), row2("10.0.1.7", B, 0, 40000, n=100)], [sess("10.0.1.7", A, 0, 40000), sess("10.0.1.7", B, 0, 40000)], fl)
assert r["conflicts"] == [], "changes hours apart are bursts, not continuous alternation"
k, r = kinds2([row2("10.0.1.8", A, 0, 7200, n=100), row2("10.0.1.8", B, 0, 7200, n=100)], [sess("10.0.1.8", A, 0, 7200), sess("10.0.1.8", B, 0, 7200)], flipset("10.0.1.8", A, B, 4))
assert r["conflicts"] == [], "only 4 changes"

# ---------------------------------------------------------------- review fixes
# 17) a DHCP proof is usually ONE instant (start == end): it must count when it falls inside the ARP session (it used to be ignored)
rows = [row2("10.0.0.20", R, 0, 3600), row2("10.0.0.21", R, 0, 3600), row2("10.0.0.20", Q, 1800, 1800, "dhcp")]
ss = [sess("10.0.0.20", R, 0, 3600), sess("10.0.0.21", R, 0, 3600), sess("10.0.0.20", Q, 1800, 1800, "dhcp")]
k, r = kinds2(rows, ss)
assert k[R] == "lender" and r["macs"][R]["behind"] == [Q], "a point proof inside the session proves a client behind"
ss_far = [sess("10.0.0.20", R, 0, 3600), sess("10.0.0.21", R, 0, 3600), sess("10.0.0.20", Q, 3600 + 2 * mc.PROOF_SLACK_S, 3600 + 2 * mc.PROOF_SLACK_S, "dhcp")]
assert kinds2(rows, ss_far)[0][R] == "multi_address", "a proof far outside the slack does not count"
ss_edge = [sess("10.0.0.20", R, 0, 3600), sess("10.0.0.21", R, 0, 3600), sess("10.0.0.20", Q, 3600 + mc.PROOF_SLACK_S, 3600 + mc.PROOF_SLACK_S, "dhcp")]
assert kinds2(rows, ss_edge)[0][R] == "lender", "exactly at the slack still counts"

# 18) touching sessions: the same instant at two addresses is simultaneous (one batch saw both); a gap is not
assert mc.max_simultaneous([(0, 10, "a"), (10, 20, "b")]) == 2 and mc.max_simultaneous([(0, 10, "a"), (11, 20, "b")]) == 1
assert mc.max_simultaneous([(0, 10, "a"), (5, 20, "b"), (8, 9, "c")]) == 3 and mc.max_simultaneous([]) == 0

# 19) conflict thresholds at their edges: 6 changes conflict, 5 do not; a median gap of 900 s conflicts, 901 s does not
rows19 = [row2("10.0.2.1", A, 0, 90000, n=500), row2("10.0.2.1", B, 0, 90000, n=500)]
ss19 = [sess("10.0.2.1", A, 0, 90000), sess("10.0.2.1", B, 0, 90000)]
assert kinds2(rows19, ss19, flipset("10.0.2.1", A, B, 6, step=60.0))[1]["conflicts"], "6 changes"
assert not kinds2(rows19, ss19, flipset("10.0.2.1", A, B, 5, step=60.0))[1]["conflicts"], "5 changes"
assert kinds2(rows19, ss19, flipset("10.0.2.1", A, B, 8, step=float(mc.CONFLICT_MAX_MEDIAN_GAP_S)))[1]["conflicts"], "median exactly at the limit"
assert not kinds2(rows19, ss19, flipset("10.0.2.1", A, B, 8, step=mc.CONFLICT_MAX_MEDIAN_GAP_S + 1.0))[1]["conflicts"], "median just above the limit"
assert not kinds2(rows19, ss19, [dict(f, gap=3600.0) for f in flipset("10.0.2.1", A, B, 100, step=30.0)])[1]["conflicts"], "changes after long silences are a MAC coming back"
assert kinds2(rows19, ss19, [dict(f, gap=0.0) for f in flipset("10.0.2.1", A, B, 100, step=30.0)])[1]["conflicts"]

# 20) a MAC with two addresses and no DHCP proof (a repeater we cannot prove) alternating with a client's MAC: possible, not certain; stays multi_address
rows20 = [row2("10.0.3.1", R, 0, 7200), row2("10.0.3.2", R, 0, 7200), row2("10.0.3.2", A, 0, 7200)]
ss20 = [sess("10.0.3.1", R, 0, 7200), sess("10.0.3.2", R, 0, 7200), sess("10.0.3.2", A, 0, 7200)]
k, r = kinds2(rows20, ss20, flipset("10.0.3.2", R, A, 60))
assert r["conflicts"] == [] and r["possible_conflicts"] == [{"ip": "10.0.3.2", "macs": [R, A]}] and k[R] == "multi_address" and k[A] == "normal", (k, r)
print("TUTTO OK")
