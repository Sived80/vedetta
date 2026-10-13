"""Golden-master test of dhcp.mobile_score (DHCP part of the "mobile" score) and dhcp._Listener.datagram_received (what a received DHCP packet adds to the memory): 4000 generated cases each.
mobile_score runs on a synthetic `seen` memory (every OS fingerprint, vendor classes, host names, private and universal MACs, missing and empty entries, mixed-case and invalid MACs).
datagram_received runs on a listener without a socket: `parse`, the clock (`time`), `_save` and the logger are replaced by in-memory fakes that record every call, so the order and the
number of the calls count too; the memory, the DHCP servers dictionary and the recorded calls must match tests/golden/dhcp_mobile.json, written from the code as it was before the two
methods were split (the key order of the dictionaries counts).
Regenerate only on purpose:  DHCPMOBILE_GOLDEN_UPDATE=1 python tests/check_dhcp_golden.py"""
import copy
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import dhcp  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "dhcp_mobile.json"
N = 4000
rng = random.Random(97531)


def pick(seq):
    return seq[rng.randrange(len(seq))]


# ---------------------------------------------------------------- mobile_score
MACS = ["aa:bb:cc:00:00:01", "02:bb:cc:00:00:02", "06:bb:cc:00:00:03", "0a:bb:cc:00:00:04", "0e:bb:cc:00:00:05", "f0:bb:cc:00:00:06", "10:bb:cc:00:00:07", "d2:bb:cc:00:00:08"]
PRLS = ["1,121,3,6,15,119,252", "1,121,3,6,15,119,252,95,44,46", "1,121,3,6,15,119,252,44", "1,121,3,6,15,119,252,95", "1,121,3,6,15,119", "1,3,6,15,26,28,51,58,119",
        "1,3,6,15,31,33,43,44,46,47,119,121,249,252", "1,28,2,3,15,6,12,119", "28,12", "26,28,51", "1,3,6", "", None, "abc", "1,x,3", "249,252", "3,121,1,252", "12,28,26,51,58"]
VCS = ["android-dhcp-13", "MSFT 5.0", "dhcpcd-9.4.1", "udhcp 1.35", "", None, "ChromeOS", "chrome os", "other", "MSFT", "Android-DHCP-9", "ChromeOS 14"]
HOSTS = ["iPhone-de-Anna", "iPad", "IPHONE", "android-abc123", "Android-xyz", "laptop", "", None, " iphone", "ipadmini", "androidx", "android-", "DESKTOP-1"]
QUERY_MACS = MACS + [m.upper() for m in MACS[:4]] + [None, "", "garbage", "zz:00", "G2:aa", "2", "0x:00"] + ["aa:bb:cc:00:00:99", "02:00:00:00:00:99"]


def entry():
    if rng.random() < 0.05:
        return {}
    e = {}
    if rng.random() < 0.85:
        e["prl"] = pick(PRLS)
    if rng.random() < 0.7:
        e["vendor_class"] = pick(VCS)
    if rng.random() < 0.7:
        e["hostname"] = pick(HOSTS)
    return e


mob_out = []
reasons = {}
scores = {}
for _ in range(N):
    dhcp.seen.clear()
    for m in MACS:
        if rng.random() < 0.7:
            dhcp.seen[m] = entry()
    mac = pick(QUERY_MACS)
    name_mobile = pick([True, False, False])
    has_ports = pick([True, False, None])
    try:
        r = list(dhcp.mobile_score(mac, name_mobile, has_ports))
        mob_out.append(r)
        reasons[r[1]] = reasons.get(r[1], 0) + 1
        scores[r[0]] = scores.get(r[0], 0) + 1
    except Exception as exc:
        mob_out.append({"exception": type(exc).__name__})

# ---------------------------------------------------------------- datagram_received
calls = []
clock = [1000.0]


def fake_time():
    clock[0] += 0.37
    calls.append(["time"])
    return clock[0]


dhcp.time = types.SimpleNamespace(time=fake_time)
dhcp._save = lambda: calls.append(["save"])
dhcp.logger = types.SimpleNamespace(info=lambda *a: calls.append(["log"] + list(a)))
DMACS = ["aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03"]
HN = ["host-a", "host-b", "", None, "iPhone"]
PR = ["1,3,6", "1,121,3", "", None]
IPS = ["192.168.1.5", "192.168.1.6", "", None, "0.0.0.0"]
SERVERS = ["192.168.1.1", "10.0.0.1", "", None]


def stored():
    e = {}
    for k, pool in (("hostname", HN), ("prl", PR), ("vendor_class", VCS), ("ip", IPS), ("ip_from", ["ciaddr", "requested", None]), ("client_id", ["0102", "", None]), ("ip_ts", [5, 7, None]),
                    ("seen", [1, 2, 900])):
        if rng.random() < 0.5:
            e[k] = pick(pool)
    keys = list(e)
    rng.shuffle(keys)
    return {k: e[k] for k in keys}


def new_info(previous):
    info = {}
    for k, pool in (("hostname", HN), ("prl", PR), ("vendor_class", VCS), ("ip", IPS), ("ip_from", ["ciaddr", "requested"]), ("client_id", ["0102", "", "0a0b"]),
                    ("server_id", SERVERS)):
        if rng.random() < 0.4:
            info[k] = pick(pool)
    if previous and rng.random() < 0.4:  # often the same fields again: the entry is not "changed"
        for k in ("hostname", "prl", "vendor_class", "ip", "client_id", "ip_from"):
            if k in previous and rng.random() < 0.8:
                info[k] = previous[k]
    keys = list(info)
    rng.shuffle(keys)
    return {k: info[k] for k in keys}


lis = dhcp._Listener()
lis_out = []
flags = {"none": 0, "changed": 0, "unchanged": 0, "server": 0, "ip": 0}
for _ in range(N):
    dhcp.seen.clear()
    dhcp.servers.clear()
    for m in DMACS:
        if rng.random() < 0.6:
            dhcp.seen[m] = stored()
    if rng.random() < 0.3:
        dhcp.servers["192.168.1.1"] = 5.0
    del calls[:]
    clock[0] = 1000.0 + rng.randrange(0, 5) * 0.4
    mac = pick(DMACS + ["aa:bb:cc:00:00:09"])
    if rng.random() < 0.08:
        parsed = None
    else:
        parsed = (mac, new_info(dhcp.seen.get(mac)))
    dhcp.parse = lambda data, parsed=parsed: (calls.append(["parse", data.decode()]), copy.deepcopy(parsed))[1]
    try:
        lis.datagram_received(b"pkt", ("1.2.3.4", 68))
        res = {}
    except Exception as exc:
        res = {"exception": type(exc).__name__}
    res.update(seen=list(dhcp.seen.items()), servers=list(dhcp.servers.items()), calls=copy.deepcopy(calls))
    lis_out.append(res)
    if parsed is None:
        flags["none"] += 1
    else:
        saved = any(c[0] == "save" for c in calls)
        flags["changed" if saved else "unchanged"] += 1
        flags["server"] += bool(parsed[1].get("server_id"))
        flags["ip"] += bool(parsed[1].get("ip"))

out = {"mobile": mob_out, "listener": lis_out}
text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("DHCPMOBILE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for part in ("mobile", "listener"):
    assert len(want[part]) == len(out[part]) == N
    for i, (x, y) in enumerate(zip(out[part], want[part])):
        assert json.dumps(x) == json.dumps(y), "%s case %d differs: %s" % (part, i, json.dumps([x, y])[:600])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert all(reasons.get(r, 0) > 20 for r in (None, "nome", "impronta DHCP (ios)", "impronta DHCP (android)", "nome DHCP", "MAC privato")), reasons
assert all(scores.get(s, 0) > 20 for s in (-2, -1, 0, 1, 2, 3, 4, 5)) and any(s >= 6 for s in scores), scores
assert not any(isinstance(r, dict) for r in mob_out)
assert flags["none"] > 150 and flags["changed"] > 1000 and flags["unchanged"] > 150 and flags["server"] > 300 and flags["ip"] > 500, flags
assert not any("exception" in r for r in lis_out)
print("TUTTO OK")
