"""Golden-master test of NewDeviceWatch.check (compares the MACs that ARP and DHCP show with the known ones and warns once for each new one): 3000 generated runs with every collaborator
replaced by a deterministic in-memory one - the configured devices and the cards in memory (with good, empty and invalid MACs), the lookup of the own address (known, unknown, found,
failing, returning a wrong shape), the DHCP table, the list of ignored devices, the observation and evaluation functions (the evaluation also fails or returns new devices with and
without address, hostname, brand), the own MACs, the alert setting (on, off, failing), the logger and the two callbacks - must give exactly the final state of the object (set of MACs,
baseline blocks, own address), the exception if any AND the ORDER of every call with its arguments (log lines, events, alerts, lookups) stored in tests/golden/newdevicewatch_check.json,
written from the code as it was before the method was split (digest per case plus a readable sample).
Regenerate only on purpose:  NEWDEVWATCH_GOLDEN_UPDATE=1 python tests/check_newdevicewatch_check_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import types
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import newdevicewatch  # noqa: E402
from app.storage import newdevices as real_newdevices  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "newdevicewatch_check.json"
N = 3000
rng = random.Random(6006)
LOG: list = []
SET: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def ser(x):
    if isinstance(x, (set, frozenset)):
        return {"set": sorted(x, key=repr)}
    if isinstance(x, dict):
        return {str(k): ser(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [ser(v) for v in x]
    return x


def log(*entry):
    LOG.append(ser(list(entry)))


class FakeLogger:
    @staticmethod
    def info(fmt, *args):
        log("info", fmt, [str(a) for a in args])

    @staticmethod
    def exception(fmt, *args):
        log("exception", fmt, [str(a) for a in args])


def fake_load_devices():
    log("load_devices")
    if SET["load_fails"]:
        raise OSError("no file")
    return SET["configs"]


async def fake_get_local_network():
    log("get_local_network")
    r = SET["net"]
    if isinstance(r, Exception):
        raise r
    return r


def fake_observed_macs(arp, seen, skip_ips):
    log("observed_macs", sorted(arp), sorted(seen), sorted(skip_ips, key=repr))
    if SET["observed_fails"]:
        raise RuntimeError("observed")
    out = {}
    for ip, host in arp.items():
        mac = host.get("mac")
        if mac and ip not in skip_ips:
            out[mac] = {"ip": ip, "hostname": (seen.get(mac) or {}).get("hostname"), "vendor": host.get("vendor")}
    return out


def fake_matches(*, mac=None, ip=None, name=None):
    log("matches", mac, ip, name)
    if SET["matches_fails"]:
        raise ValueError("matches")
    return mac[-1] in SET["ignored_digits"]


def fake_evaluate(observed, configured_ips, configured_macs, ignore_macs=frozenset(), baseline_blocks=()):
    log("evaluate", observed, configured_ips, configured_macs, ignore_macs, list(baseline_blocks))
    if SET["evaluate_fails"]:
        raise RuntimeError("evaluate")
    return SET["fresh"], SET["current"]


def fake_own_macs():
    log("own_macs")
    return {"AA:AA:AA:00:00:01"}


def fake_alerts_enabled():
    log("alerts_enabled")
    if SET["alerts_fails"]:
        raise OSError("settings")
    return SET["alerts_on"]


def emit(event):
    log("emit", event)


def emit_alert(message, key, **kwargs):
    log("emit_alert", message, key, kwargs)


dhcp_ns = types.SimpleNamespace(seen={})
newdevicewatch.logger = FakeLogger
newdevicewatch.devices_config = types.SimpleNamespace(load_devices=fake_load_devices)
newdevicewatch.netutil = types.SimpleNamespace(get_local_network=fake_get_local_network)
newdevicewatch.dhcp = dhcp_ns
newdevicewatch.blocklist = types.SimpleNamespace(matches=fake_matches)
newdevicewatch.settings = types.SimpleNamespace(alerts_enabled=fake_alerts_enabled)
newdevicewatch.newdevices = types.SimpleNamespace(normalize_mac=real_newdevices.normalize_mac, observed_macs=fake_observed_macs, evaluate=fake_evaluate, own_macs=fake_own_macs,
                                                  readable_label=real_newdevices.readable_label, event=real_newdevices.event)

MACS = ["AA:BB:CC:00:00:%02X" % i for i in range(0x10, 0x1A)]
IPS = ["192.168.1.%d" % i for i in range(2, 9)]
CARD_MACS = MACS[:5] + ["aa-bb-cc-00-00-11", "", None, "zz", "01:00:5e:00:00:01", "00:00:00:00:00:00"]
HOSTS = [None, "", "phone", "tv"]
BASE = [(), ("10.9.0.0/16",), ("10.9.0.0/16", "172.16.0.0/12")]


def fresh_device():
    d = {"mac": pick(MACS), "ip": pick(IPS + [None, ""]), "vendor": pick([None, "Acme"]), "hostname": pick(HOSTS), "brand": pick([None, "Brand"])}
    if rng.random() < 0.15:
        del d["hostname"]
    return d


def run_case():
    LOG.clear()
    macs = rng.sample(MACS, rng.randrange(0, 8))
    arp = {}
    for m in macs:
        arp[pick(IPS)] = {"mac": pick([m, m, m.lower(), "", None]), "vendor": pick([None, "Acme"])}
    arp["192.168.1.250"] = {"mac": pick(MACS)} if rng.random() < 0.3 else {}
    SET.update(load_fails=rng.random() < 0.03, observed_fails=rng.random() < 0.03, matches_fails=rng.random() < 0.02, evaluate_fails=rng.random() < 0.04,
               alerts_on=rng.random() < 0.6, alerts_fails=rng.random() < 0.03, ignored_digits=pick(["", "", "1", "13", "2468"]))
    SET["configs"] = [{"ip": pick(IPS)} for _ in range(rng.randrange(0, 4))]
    if rng.random() < 0.03:
        SET["configs"].append({})
    SET["net"] = pick([("10.0.0.0/24", "192.168.1.3"), ("x", None), ("x", ""), RuntimeError("no ip"), ("only",), None])
    SET["fresh"] = [fresh_device() for _ in range(rng.randrange(0, 4))]
    SET["current"] = [fresh_device() for _ in range(rng.randrange(0, 4))]
    dhcp_ns.seen = {m: {"hostname": pick(HOSTS)} for m in rng.sample(MACS, rng.randrange(0, 4))}
    cards = {"c%d" % i: {"mac": pick(CARD_MACS)} for i in range(rng.randrange(0, 5))}
    if rng.random() < 0.05:
        cards["bare"] = {}
    watch = newdevicewatch.NewDeviceWatch(lambda: cards, emit, emit_alert)
    watch.own_ip = pick([None, None, "192.168.1.4", "", "192.168.1.3"])
    watch.baseline_blocks = pick(BASE)
    watch.macs = frozenset(rng.sample(MACS, rng.randrange(0, 4)))
    before_macs = watch.macs
    try:
        ret = loop.run_until_complete(watch.check(arp))
        res = {"ret": ret}
    except BaseException as exc:
        res = {"exception": type(exc).__name__}
    res.update(state=ser([watch.macs, watch.baseline_blocks, watch.own_ip, watch.macs == before_macs]), log=list(LOG))
    return res


loop = asyncio.new_event_loop()
cases = [run_case() for _ in range(N)]
loop.close()
digests = [hashlib.sha1(json.dumps(c).encode()).hexdigest()[:12] for c in cases]
out = json.loads(json.dumps({"digests": digests, "sample": cases[:10]}))
if os.environ.get("NEWDEVWATCH_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(digests) == N
for i, (x, y) in enumerate(zip(digests, want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(cases[i])[:1200])
assert out["sample"] == want["sample"]
kinds = [{e[0] for e in c["log"]} for c in cases]
names = [[e[0] for e in c["log"]] for c in cases]
assert sum(1 for k in kinds if "emit_alert" in k) > 600 and sum(1 for k in kinds if "emit" in k) > 600 and sum(1 for k in kinds if "evaluate" in k) > 2000
assert sum(1 for c in cases if any(e[0] == "info" and e[1].startswith("Nuovo dispositivo") for e in c["log"])) > 400
assert sum(1 for c in cases if any(e[0] == "exception" for e in c["log"])) > 200 and sum(1 for c in cases if "exception" in c) > 20
assert sum(1 for k in kinds if "get_local_network" in k) > 800 and sum(1 for k in kinds if "get_local_network" not in k and "evaluate" in k) > 800
assert sum(1 for c in cases if c["state"][2] not in (None, "192.168.1.4", "")) > 300 and sum(1 for c in cases if c["state"][1] == []) > 2000
assert sum(1 for L in names if L.count("matches") >= 2) > 600 and sum(1 for c in cases if any(e[0] == "matches" and True for e in c["log"]) and "emit" not in {e[0] for e in c["log"]}) > 200
assert sum(1 for c in cases if any(e[0] == "evaluate" and e[5] for e in c["log"])) > 500
assert sum(1 for c in cases if any(e[0] == "emit_alert" and e[3].get("ip") == "-" for e in c["log"])) > 100 and sum(1 for c in cases if c["state"][3]) > 300
assert sum(1 for k in kinds if "evaluate" in k and "alerts_enabled" not in k) > 50
print("TUTTO OK")
