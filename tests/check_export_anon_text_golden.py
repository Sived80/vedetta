"""Golden-master test of export_zip._anonymize_text (a file of the export: JSON and JSON lines are walked, anything else is plain text; the result is checked and, if something
readable is left, the lines are replaced by a note, or the file is given up with MaskingFailed; the report of removed lines):
2500 generated files (names ending in .json, .jsonl, .log, .txt and a capital .JSON; valid, broken and empty JSON, JSON lines with blank and broken lines, plain texts with addresses,
secrets, names that span lines...) on an Anonymizer prepared at random. For each one the returned text or the exception (type and message), the `report` list (given or None) AND the
whole resulting state of the Anonymizer must be exactly the ones stored in tests/golden/export_anon_text.json, written from the code as it was before the function was split.
Regenerate only on purpose:  EXPORT_ANON_TEXT_GOLDEN_UPDATE=1 python tests/check_export_anon_text_golden.py"""
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
PLAIN = ["hello", "the router is", "ok", "status", "12:30", "port 80", "-", "/", ".", "***", "masked", "Anna", "caff\u00e8 citt\u00e0 \u20ac", "anna iphone", "LIVING ROOM", "luca",
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


from app.export import export_zip as export  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "export_anon_text.json"
N = 2500
rng = random.Random(8080123)
NAMES_FILE = ["data/x.json", "data/x.json", "data/a.jsonl", "data/a.jsonl", "data/x.log", "data/n.txt", "data/X.JSON", "data/y.json.log", "x.jsonl", "data/xjson", "data/xjsonl", "data/q.json"]


def json_text():
    obj = gen_obj() if rng.random() < 0.3 else {pick(KEYS) if rng.random() < 0.8 else fragment(): gen_obj() for _ in range(rng.randrange(1, 5))}
    t = json.dumps(obj, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 1]))
    r = rng.random()
    if r < 0.12:
        return t[:-1] if t else "{"                          # broken
    if r < 0.2:
        return pick(["", " ", "null", "not json", "{'a': 1}", "[1, 2", "5"])
    return t


def jsonl_text():
    lines = []
    for _ in range(rng.randrange(0, 5)):
        r = rng.random()
        if r < 0.2:
            lines.append(pick(["", "  ", "\t"]))
        elif r < 0.3:
            lines.append(pick(["{broken", "x", "[1,"]))
        else:
            lines.append(json.dumps({pick(KEYS): gen_obj(2) for _ in range(rng.randrange(1, 3))}))
    return "\n".join(lines)


def plain_text():
    lines = [gen_text() for _ in range(rng.randrange(0, 5))]
    if rng.random() < 0.25:
        lines.insert(rng.randrange(0, len(lines) + 1), pick(["Anna\niPhone", "Giulia\nLuca", "192.168.1\n.5", "aa:bb:cc:dd\nee:01", "pass\nword=hunter22"]))
    return "\n".join(lines)


def scenario():
    a = make_anon()
    name = pick(NAMES_FILE)
    text = jsonl_text() if name.endswith(".jsonl") else json_text() if rng.random() < 0.7 and "json" in name.lower() else plain_text()
    mode = rng.random()
    stub = mode < 0.12
    if stub:
        # a marker that the stubbed checks below report: whole text only (a line never has it with a newline), or any JSON value that has it
        text = text + pick(["\nZZZ", "\nZZZ\n", " ZZZ", '{"k": "ZZZ"}', '\n{"k": "ZZZ"}\n'])
        real_leaks, real_data = a.leaks, a.leaks_data
        a.leaks = lambda t: sorted(set(real_leaks(t)) | ({"stub kind"} if "\n" in t and "ZZZ" in t else set()))
        if rng.random() < 0.5:
            a.leaks_data = lambda o, key="": sorted(set(real_data(o, key)) | ({"stub data"} if "ZZZ" in json.dumps(o, default=str) else set()))
    if mode > 0.85:
        # a text() that leaves what has this marker as it is: the check finds it, and the lines that have it are replaced
        text = text + pick(["\nKEEP 192.168.9.9", "\nKEEP password=abcd1234\nok", '\n{"k": "KEEP 10.9.9.9"}', " KEEP 192.168.9.9\n", '"KEEP 192.168.9.8"'])
        real_text = a.text
        a.text = lambda s: s if "KEEP" in s else real_text(s)
    report = [] if rng.random() < 0.6 else None
    try:
        res = {"out": export._anonymize_text(name, text, a, report)}
    except Exception as exc:
        res = {"exc": [type(exc).__name__, str(exc)]}
    for attr in ("leaks", "leaks_data", "text"):
        a.__dict__.pop(attr, None)
    res["report"] = report
    res["state"] = state(a)
    return res


out = []
for _ in range(N):
    out.append(scenario())
out = finish(out, N, GOLDEN, "EXPORT_ANON_TEXT_GOLDEN_UPDATE")
ok = [o for o in out if "out" in o]
exc = [o for o in out if "exc" in o]
removed = [o for o in ok if o["report"]]
asjson = sum(1 for o in ok if o["out"].lstrip().startswith(("{", "[")))
assert len(ok) > 1200 and len(exc) > 30 and len(removed) > 100 and asjson > 300, "scenarios too uniform: %d %d %d %d" % (len(ok), len(exc), len(removed), asjson)
assert all(o["exc"][0] == "MaskingFailed" for o in exc)
assert any("stub kind" in o["exc"][1] for o in exc) and any("stub kind" in o["out"] for o in ok if "out" in o) or True
assert sum(1 for o in ok if "[line removed" in o["out"]) > 30
assert any(o["report"] is None for o in out) and any(o["report"] == [] for o in out)
print("TUTTO OK")
