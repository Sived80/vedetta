"""Golden-master test of Anonymizer.data and Anonymizer.repair_data (the replacement and the repair over parsed JSON: keys are masked too, the fields that describe the device
are kept, secret and private fields become "***", lists and dictionaries nest, non-string keys and values stay as they are):
1800 generated JSON-like objects (nested dictionaries and lists, addresses, MACs, e-mails, domains, IPv6, secrets and names in values and in keys, every kind of key) on an
Anonymizer prepared at random. For each one data() on one instance and repair_data() on another (sometimes on the already masked object, with a path and a key) must give exactly
the results AND the whole resulting state stored in tests/golden/anon_data.json, written from the code as it was before the methods were split. The order of the keys of the
returned dictionaries counts.
Regenerate only on purpose:  ANON_DATA_GOLDEN_UPDATE=1 python tests/check_anon_data_golden.py"""
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402
from app.export.anonymize import Anonymizer  # noqa: E402


def ser(x):
    """Stable form of any value: dicts keep their key order, sets are sorted, patterns are their source."""
    if isinstance(x, dict):
        return {"d": [[ser(k), ser(v)] for k, v in x.items()]}
    if isinstance(x, (list, tuple)):
        return [ser(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return {"s": sorted((ser(v) for v in x), key=json.dumps)}
    if isinstance(x, re.Pattern):
        return {"re": x.pattern}
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    return {"obj": repr(x)}


def state(a):
    return {k: ser(v) for k, v in sorted(vars(a).items())}


def pick(seq):
    return seq[rng.randrange(len(seq))]


BRAND_KEYS = sorted(anonymize._brand_keys())[:30]
NAMES = ["Anna's iPhone", "Annas-iPhone", "anna_s_iphone", "Giulia", "giulia", "Marco PC", "Living Room", "Soggiorno", "Cucina", "Luca",
         "Luca Phone", "pve", "nas", "ab", "unknown", "Home Assistant", "localhost", "12345", "1-2-3", "", None, 0, "Shelly 1PM", "shelly-plug",
         "Node RED", "nodered", "Apple mobile", "Philips Hue", "iPad di Sara", "Sara", "Kitchen cam", "Echo Dot", "ESP_8266-ab12", "TV",
         "Samsung TV", "Samsung", "Printer Office", "HP-Printer", "192.168.1.5", "True", "Mac", "MacBook Pro Davide", "Davide", "Pixel 7",
         "Android-phone", "RPI4", "xxxx", "Ottavio's Room", "Ottavio", "Elan lamp", "\u00c9lan lamp", "\u00c9lan", "TP-Link AP", "Gate Motor",
         "  padded name  ", "Router di Carla", "Carla", "xbox", "Thermo Stat", "Mario Rossi", "Rossi", "Lab-7", "Lab 7", "Fritz 7490 box", "   ", " 192.168.1.5 ", "pc1", "a-b", "Ab1", "gw 192.168.1.5", "192.168.1.5 box", "x1c"]
AREAS = ["Living Room", "Cucina", "Garage", "Soggiorno", "Ottavio's Room", "Studio", "Attic", "", None, "---", "Sara"]
BRANDS = ["Apple", "Philips", "Node-RED", "Node RED", "", None, "!!!", "\u00c9lan", "Shelly", "TP-Link", "  ", "Samsung", "Elan", "Mac", "Fritz 7490"]
HINTS = [None, "", "router", "server", "pc", "phone", "media", "audio", "iot", "printer", "bogus"]
ICONS = [None, "", "server", "help", "thermostat", "gate", "camera", "Camera_2", "---", "garage-door", "lightbulb", "a b"]
IPS = ["192.168.1.5", "192.168.1.200", "192.168.7.9", "172.16.0.1", "172.31.9.9", "172.32.0.1", "172.15.1.1", "10.0.0.5", "10.1.2.3", "8.8.8.8",
       "1.1.1.1", "1.2.3.4", "93.184.216.34", "203.0.113.5", "100.64.0.1", "169.254.1.1", "224.0.0.1", "127.0.0.1", "0.0.0.0", "255.255.255.255",
       "300.1.1.1", "256.256.256.256", "11.22.33.44", "192.168.1.256", "198.51.100.7", "240.0.0.1", "192.168.2.9", "192.168.0.1"]
VERS = ["version 1.2.3.4", "v5.6.7.8", "fw: 9.9.9.10", "Server 4.5.6.7", "DISCOVER 4.4.4.5", "build=12.34.56.78", "release 20.30.40.50", "ver 7.7.7.7"]
SEPIPS = ["192-168-1-5", "192_168_1_5", "172-16-0-1", "172_31_5_9", "172-32-0-1", "10-0-0-5", "10-06-12-30", "192-168-1-256", "192-168-1-300",
          "172-20-1-2", "192-168-7-9", "1-2-3-4", "192_168-1-5", "scan-192-168-1-5", "192-168-1-255", "172-16-0-256"]
MACS = ["aa:bb:cc:dd:ee:01", "AA:BB:CC:DD:EE:01", "aa-bb-cc-dd-ee-02", "AA-BB-CC-DD-EE-02", "aabbccddeeff", "AABBCCDDEEFF", "00:11:22:33:44:55",
        "001122334455", "de:ad:be:ef:00:01", "e8:db:84:12:34:56", "e8db84123456", "12:34:56:78:9a:bc", "ab:cd:ef:01:02:03", "Aa:bB:cC:dD:eE:03"]
EMAILS = ["bob@example.com", "Bob@Example.com", "x@masked.invalid", "email-1@masked.invalid", "a.b+c@home.lan"]
DOMS = ["nas.home.example.com", "github.com", "api.github.com", "dashboard.log", "app.state", "my-family.dyndns.org", "host.local", "router.lan",
        "not a domain", "HOST.LOCAL"]
V6 = ["fe80::1:2:3:4", "2001:db8::5", "2001:db8::1", "::1", "::", "ff02::c", "2a01:1:2:3:4:5:6:7", "9b:e9:0b:ab:cd:ef:01:23", "12:34:56", "fd00::1"]
SECRETS = ["password=hunter22", "token: abcd1234", "Authorization: Bearer abc.def", "api_key=ab", "api-key = \"zzzz9\"", "passwd:***",
           "http://user:pw@host/x", "https://u:p@10.0.0.5:80/", "secret=abc;next", "pass=abcd", "token=***"]
PLAIN = ["hello", "the router is", "ok", "status", "12:30", "port 80", "-", "/", ".", "***", "masked", "Anna", "anna iphone", "LIVING ROOM", "luca",
         "Giulia's iPad", "Soggiorno", "Sara", "Elan", "xbox"]
SEPS = [" ", ", ", "-", "/", "", "\n", " = ", ": "]
KEYS = ["icon", "type", "name", "password", "Token", "api_key", "user", "username", "mqtt_user", "mqtt_host", "domains", "model", "ssh_hostkey",
        "family", "note", "secret_x", "host", "ip", "mac", "Authorization", "kind", "", "x", "brand", "credential"]


def alias_list(n=None):
    return [pick(NAMES + BRAND_KEYS) for _ in range(rng.randrange(0, 5) if n is None else n)]


def fragment():
    pool = rng.randrange(10)
    if pool == 0:
        return pick(IPS)
    if pool == 1:
        return pick(VERS)
    if pool == 2:
        return pick(SEPIPS)
    if pool == 3:
        return pick(MACS)
    if pool == 4:
        return pick(EMAILS + DOMS)
    if pool == 5:
        return pick(V6 + SECRETS)
    if pool == 6:
        return str(pick(NAMES) or "")
    return pick(PLAIN)


def gen_text():
    parts = []
    for _ in range(rng.randrange(0, 6)):
        parts.append(fragment())
        parts.append(pick(SEPS))
    return "".join(parts)


def make_anon(public=True):
    """An anonymizer prepared with a random mix of registered addresses, MACs, names and areas (at most one known public address:
    the set they are kept in has no stable order)."""
    a = Anonymizer()
    did_public = not public
    for _ in range(rng.randrange(0, 7)):
        op = rng.randrange(7)
        if op == 0:
            a.add_ip(pick(IPS + [None, "bad"]))
        elif op == 1:
            a.add_mac(pick(MACS + [None, "zz", ""]))
        elif op == 2:
            a.add_area(pick(AREAS))
        elif op == 3:
            a.add_device(alias_list(), pick(HINTS), pick(BRANDS), pick(ICONS))
        elif op == 4:
            a.add_names(alias_list(), pick(BRANDS), tuple(alias_list()))
        elif op == 5 and not did_public:
            did_public = True
            a.add_public_ip(pick(IPS + [None, "bad"]))
        else:
            a.add_device(alias_list(), pick(HINTS))
    return a


def gen_obj(depth=0):
    r = rng.randrange(12)
    if depth >= 3 or r < 5:
        return gen_text()
    if r == 5:
        return pick([None, 0, 5, 1.5, True, False, "", "***"])
    if r < 8:
        return [gen_obj(depth + 1) for _ in range(rng.randrange(0, 4))]
    out = {}
    for _ in range(rng.randrange(0, 5)):
        kind = rng.randrange(8)
        if kind == 0:
            k = rng.randrange(0, 4)
        elif kind == 1:
            k = fragment()
        else:
            k = pick(KEYS)
        out[k] = gen_obj(depth + 1)
    if rng.random() < 0.08:
        out["192.168.1"] = gen_obj(depth + 1)         # the pieces of an address in two keys: only a key list joined by "" would make one
        out[".5"] = gen_obj(depth + 1)
    return out


def finish(out, N, GOLDEN, env):
    out = json.loads(json.dumps(out))
    if os.environ.get(env) or not GOLDEN.exists():
        GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
        print("golden written")
    want = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(want) == len(out) == N
    for i, (x, y) in enumerate(zip(out, want)):
        assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:700])
    return out

GOLDEN = Path(__file__).parent / "golden" / "anon_data.json"
N = 1800
rng = random.Random(97531)


def scenario():
    obj = gen_text() if rng.random() < 0.12 else gen_obj() if rng.random() < 0.25 else {pick(KEYS) if rng.random() < 0.8 else fragment(): gen_obj() for _ in range(rng.randrange(1, 5))}
    key = pick(["", "", "", "icon", "password", "user", "name", "note", "domains", "api_key"])
    a = make_anon()
    got = a.data(obj, key)
    first = {"data": ser(got), "state": state(a)}
    b = make_anon()
    src = obj if rng.random() < 0.6 else b.data(obj, key)
    path = pick(["", "", "/root", "/a/b"])
    key2 = pick(["", "", "", "icon", "password", "name", "kind"])
    res = b.repair_data(src, key2, path)
    return {"data": first, "repair": ser(res), "repair_state": state(b)}


out = []
for _ in range(N):
    try:
        out.append(scenario())
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = finish(out, N, GOLDEN, "ANON_DATA_GOLDEN_UPDATE")
assert not any("exception" in o for o in out)


def walk(x):
    if isinstance(x, dict) and set(x) == {"d"}:
        for k, v in x["d"]:
            yield k
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)
    else:
        yield x


masked = sum(1 for o in out if any(isinstance(v, str) and ("masked.invalid" in v or v.startswith("10.") or "203.0.113" in v or v.startswith("Anna")) for v in walk(o["data"]["data"])))
secret = sum(1 for o in out if "***" in json.dumps(o["data"]["data"]))
fixed = sum(1 for o in out if o["repair"][1] > 0)
left = sum(1 for o in out if o["repair"][2])
dicts = sum(1 for o in out if isinstance(o["data"]["data"], dict))
intkeys = sum(1 for o in out if any(isinstance(k, int) for k in walk(o["data"]["data"])))
assert masked > 300 and secret > 400 and fixed > 600 and left > 100 and dicts > 600, "scenarios too uniform: %d %d %d %d %d" % (masked, secret, fixed, left, dicts)
assert any("/root" in json.dumps(o["repair"][2]) for o in out) and any("/a/b/" in json.dumps(o["repair"][2]) for o in out)
print("TUTTO OK")
