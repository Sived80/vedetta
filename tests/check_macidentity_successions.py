"""1.0 step P10 (decisions 1A, 2A of 13/11): a private MAC that rotates. macidentity.successions(features, only) finds the pairs (old -> new) where
a new private MAC is the same device as a private MAC that stopped before it began: zone "same" of the linker (strong evidence: a shared
client identifier, or name AND fingerprint), never active together, the old one finished before the new one started. An ambiguous case (two
candidates on either side) gives nothing. Pure, no network.
    python tests/check_macidentity_successions.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import macidentity  # noqa: E402

OLD, NEW = "DA:00:00:00:00:01", "DA:00:00:00:00:02"      # 0xDA: locally administered (private)
H = 3600.0


def dev(host=None, fp=None, cid=None, start=0.0, end=H, ip="192.168.1.20") -> dict:
    f = {"first": start, "last": end, "ips": [ip], "sessions": [(start, end, (ip,))]}
    for k, v in (("hostname", host), ("fingerprint", fp), ("client_id", cid)):
        if v:
            f[k] = v
    return f


def population() -> dict:
    """Other devices of a home network: names and fingerprints that make the phone's own values rare."""
    out = {}
    for i, (host, fp) in enumerate([("tv-sala", "linux|1,3"), ("printer", "hp|1,3,6"), ("laptop-marco", "win|1,3,6,15"),
                                    ("ipad", "ios|1,121,3"), ("nas", "linux|1,3,6"), ("camera-1", "cam|1,3"), ("camera-2", "cam|1,3")]):
        out["3C:00:00:00:01:%02X" % i] = dev(host, fp, start=0.0, end=10 * H, ip="192.168.1.%d" % (100 + i))
    return out


def run(old: dict, new: dict, extra: dict | None = None, only=None) -> dict:
    feats = {**population(), OLD: old, NEW: new, **(extra or {})}
    return macidentity.successions(feats, only)


PHONE = ("anna-phone", "android|1,3,6,15,26")

# 1. the phone rotates its MAC when it reconnects: same name and fingerprint, the new one starts where the old one stopped -> a succession
assert run(dev(*PHONE, start=0, end=H), dev(*PHONE, start=H + 60, end=3 * H, ip="192.168.1.31")) == {NEW: OLD}
# 2. a shared client identifier is enough, even days apart and without a name
assert run(dev(cid="01:aa:bb", start=0, end=H), dev(cid="01:aa:bb", start=3 * 86400, end=3 * 86400 + H)) == {NEW: OLD}
# 3. two phones of the same model with different names: never one device
assert run(dev("anna-phone", PHONE[1], start=0, end=H), dev("luca-phone", PHONE[1], start=H + 60, end=3 * H)) == {}
# 4. the same generic name only, no fingerprint: not strong enough (decision 2A: "possible" does nothing)
assert run(dev("iPhone", start=0, end=H), dev("iPhone", start=H + 60, end=3 * H)) == {}
# 5. only private MACs rotate: a normal (global) MAC is never the old or the new one
NORMAL = "3C:00:00:00:00:09"
feats = {**population(), NORMAL: dev(*PHONE, start=0, end=H), NEW: dev(*PHONE, start=H + 60, end=3 * H)}
assert macidentity.successions(feats) == {}, "old MAC not private"
feats = {**population(), OLD: dev(*PHONE, start=0, end=H), NORMAL: dev(*PHONE, start=H + 60, end=3 * H)}
assert macidentity.successions(feats) == {}, "new MAC not private"
# 6. active together (at different addresses): two devices
assert run(dev(*PHONE, start=0, end=2 * H), dev(*PHONE, start=H, end=3 * H, ip="192.168.1.31")) == {}
# 7. the "new" one began before the "old" one: the pair is read the right way round, never backwards
assert run(dev(*PHONE, start=H + 60, end=3 * H), dev(*PHONE, start=0, end=H)) == {OLD: NEW}
# 8. ambiguity gives nothing: two old MACs that could be the new one, or one old MAC with two possible successors
OLD2 = "DA:00:00:00:00:03"
assert run(dev(cid="01:aa:bb", start=0, end=H), dev(cid="01:aa:bb", start=5 * H, end=6 * H),
           {OLD2: dev(cid="01:aa:bb", start=2 * H, end=3 * H)}) == {}, "a chain old -> old2 -> new is not resolved in one step"
NEW2 = "DA:00:00:00:00:04"
assert run(dev(cid="01:aa:bb", start=0, end=H), dev(cid="01:aa:bb", start=2 * H, end=3 * H, ip="192.168.1.31"),
           {NEW2: dev(cid="01:aa:bb", start=2 * H, end=3 * H, ip="192.168.1.32")}) == {}
# 9. `only`: just the successors asked for (the MACs the caller cares about), the others are not judged
args = (dev(*PHONE, start=0, end=H), dev(*PHONE, start=H + 60, end=3 * H))
assert run(*args, only={NEW}) == {NEW: OLD} and run(*args, only={"DA:00:00:00:00:77"}) == {} and run(*args, only=set()) == {}
# 11. the sources are timed differently (a DHCP packet at its own time, a neighbour entry at "now minus its age"): the old MAC may look active a few
#     seconds after the new one began (S39: 8 s). Up to SUCCESSION_OVERLAP_S that is a handover, not two devices at once; longer is two devices
assert run(dev(*PHONE, start=0, end=H + 8), dev(*PHONE, start=H, end=3 * H, ip="192.168.1.31")) == {NEW: OLD}, "8 s of overlap"
assert macidentity.SUCCESSION_OVERLAP_S == 60
assert run(dev(*PHONE, start=0, end=H + 61), dev(*PHONE, start=H, end=3 * H, ip="192.168.1.31")) == {}, "61 s: together"
# 10. name and fingerprint with a long pause between: only "possible" in a small network, nothing (the client identifier does it, case 2)
assert run(dev(*PHONE, start=0, end=H), dev(*PHONE, start=2 * H, end=3 * H)) == {}
assert macidentity.successions({}) == {}

print("check_macidentity_successions OK")
