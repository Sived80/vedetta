"""Golden-master test of Anonymizer._leaks_addresses, leaks_data and text_note (what is still readable in masked text: home and public IPv4 addresses in dotted and dashed forms,
the known public address, well known DNS, version numbers, our placeholders; the same over parsed JSON, keys joined included; and the note written by the person, where a word of a
known device or area name is masked):
2500 generated cases on an Anonymizer prepared at random. For each one the list yielded by _leaks_addresses (in order), leaks_data on a raw and on an already masked object, and
text_note on notes made of words of the registered names AND the whole resulting state must be exactly the ones stored in tests/golden/anon_leaks.json, written from the code as it
was before the methods were split.
Regenerate only on purpose:  ANON_LEAKS_GOLDEN_UPDATE=1 python tests/check_anon_leaks_golden.py"""
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
         "  padded name  ", "Router di Carla", "Carla", "xbox", "Thermo Stat", "Mario Rossi", "Rossi", "Lab-7", "Lab 7", "Fritz 7490 box", "   ", " 192.168.1.5 ", "pc1", "a-b", "Ab1", "gw 192.168.1.5", "192.168.1.5 box", "x1c", "Unknown Box9", "Localhost Server", "Philips Hue Anna", "Esp ab12 Giulia", "Annaiphone", "Lucaxbox"]
AREAS = ["Living Room", "Cucina", "Garage", "Soggiorno", "Ottavio's Room", "Studio", "Attic", "", None, "---", "Sara"]
BRANDS = ["Apple", "Philips", "Node-RED", "Node RED", "", None, "!!!", "\u00c9lan", "Shelly", "TP-Link", "  ", "Samsung", "Elan", "Mac", "Fritz 7490"]
HINTS = [None, "", "router", "server", "pc", "phone", "media", "audio", "iot", "printer", "bogus"]
ICONS = [None, "", "server", "help", "thermostat", "gate", "camera", "Camera_2", "---", "garage-door", "lightbulb", "a b"]
IPS = ["192.168.1.5", "192.168.1.200", "192.168.7.9", "172.16.0.1", "172.31.9.9", "172.32.0.1", "172.15.1.1", "10.0.0.5", "10.1.2.3", "8.8.8.8",
       "1.1.1.1", "1.2.3.4", "93.184.216.34", "203.0.113.5", "100.64.0.1", "169.254.1.1", "224.0.0.1", "127.0.0.1", "0.0.0.0", "255.255.255.255",
       "300.1.1.1", "256.256.256.256", "11.22.33.44", "192.168.1.256", "198.51.100.7", "240.0.0.1", "192.168.2.9", "192.168.0.1", "203.0.114.9", "203.1.2.3", "172.31.255.1", "172.16.0.0", "192.169.1.5", "10.168.1.1", "11.22.33.255", "255.1.1.1", "192.168.255.1"]
VERS = ["version 1.2.3.4", "v5.6.7.8", "fw: 9.9.9.10", "Server 4.5.6.7", "DISCOVER 4.4.4.5", "build=12.34.56.78", "release 20.30.40.50", "ver 7.7.7.7"]
SEPIPS = ["192-168-1-5", "192_168_1_5", "172-16-0-1", "172_31_5_9", "172-32-0-1", "10-0-0-5", "10-06-12-30", "192-168-1-256", "192-168-1-300",
          "172-20-1-2", "192-168-7-9", "1-2-3-4", "192_168-1-5", "scan-192-168-1-5", "192-168-1-255", "172-16-0-256", "192-169-1-5", "10-168-1-5", "192-168-255-5", "172-16-255-255", "172-15-1-1"]
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

GOLDEN = Path(__file__).parent / "golden" / "anon_leaks.json"
N = 2500
rng = random.Random(2468013)
WORDS = sorted({w for n in NAMES if isinstance(n, str) for w in re.split(r"[^A-Za-z]+", n) if w} | {"Anna", "Annas", "hello", "Rossi", "xbox", "iphone"})


def address_text(a):
    parts = []
    for _ in range(rng.randrange(1, 9)):
        r = rng.randrange(6)
        if r == 0:
            parts.append(pick(IPS))
        elif r == 1:
            parts.append(pick(SEPIPS))
        elif r == 2:
            parts.append(pick(VERS))
        elif r == 3 and a._public_known:
            parts.append(sorted(a._public_known)[0])
        elif r == 4:
            parts.append(gen_text())
        else:
            parts.append(pick(["x" + pick(IPS), pick(IPS) + "9", pick(IPS) + ".7", "a" + pick(SEPIPS) + "0", "ip=" + pick(IPS)]))
        parts.append(pick(SEPS))
    return "".join(parts)


def note(a):
    own = [w for k in list(a._names) + list(a._areas) for w in k.split("-")] or WORDS
    parts = [pick(own) if rng.random() < 0.45 else pick(WORDS) if rng.random() < 0.7 else fragment() for _ in range(rng.randrange(1, 7))]
    out = pick([" ", "'s ", " - ", "", "x", "1"]).join(parts)
    return pick([out, out.upper(), out.lower(), None, "", out + "!"])


def scenario():
    a = make_anon()
    text = address_text(a)
    if rng.random() < 0.3:
        text = a.text(text)
    res = {"addr": list(a._leaks_addresses(text))}
    obj = gen_obj() if rng.random() < 0.3 else {pick(KEYS) if rng.random() < 0.8 else fragment(): gen_obj() for _ in range(rng.randrange(1, 5))}
    key = pick(["", "", "", "icon", "name", "domains", "password"])
    res["data_raw"] = a.leaks_data(obj, key)
    res["data_masked"] = a.leaks_data(a.data(obj, key), key)
    res["notes"] = [a.text_note(note(a)) for _ in range(3)]
    res["state"] = state(a)
    return res


out = []
for _ in range(N):
    try:
        out.append(scenario())
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = finish(out, N, GOLDEN, "ANON_LEAKS_GOLDEN_UPDATE")
assert not any("exception" in o for o in out)
kinds = {k for o in out for k, _v in o["addr"]}
assert kinds == {"home network address", "public address"}, kinds
assert sum(1 for o in out if len(o["addr"]) > 2) > 300 and sum(1 for o in out if not o["addr"]) > 100
assert sum(1 for o in out if o["data_raw"]) > 1000 and sum(1 for o in out if not o["data_raw"]) > 200 and sum(1 for o in out if o["data_masked"]) > 50
assert len({x for o in out for x in o["data_raw"]}) >= 5
assert sum(1 for o in out for n in o["notes"] if n and "-" in n and "Anna" not in n) > 100
changed = sum(1 for o in out for n in o["notes"] if n and re.search(r"(Area|[A-Za-z]+)-\d", n))
assert changed > 300, "notes rarely masked: %d" % changed
print("TUTTO OK")
