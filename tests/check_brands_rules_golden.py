"""Golden-master test of brands._rules (merge of the shipped brand rules and the user's file into the lookup tables, with a cache keyed by the files' stamp), with the stamp function, the file
reader and the logger replaced by in-memory fakes that record their calls and the module cache reset in every case: 3000 generated pairs of rule files (rules from the interface valid and
invalid, aliases, name/software/battery hints with some invalid regular expressions, vendor roles, model hints, bridge/phone-only lists, strip words and places, odd value types) and cache
states (empty, same stamp with rules, same stamp without rules, other stamp) must give exactly the same tables (key order, tuple/list/set kinds, compiled patterns by text) or the same
exception, the same cache afterwards AND the same ordered calls as the code before the function was split. tests/golden/brands_rules.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  BRANDS_RULES_GOLDEN_UPDATE=1 python tests/check_brands_rules_golden.py"""
import hashlib
import json
import os
import random
import re
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import brands  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "brands_rules.json"
N = 3000
rng = random.Random(8181)
LOG: list = []
SET: dict = {}
SENTINEL = {"sentinel": True}
SER_SENTINEL = {"dict": [["sentinel", True]]}
BASE_PATH, USER_PATH = Path("base_brands.json"), Path("user_brands.json")


def pick(seq):
    return seq[rng.randrange(len(seq))]


class FakeLogger:
    @staticmethod
    def warning(fmt, *args):
        LOG.append(["warning", fmt, repr(args)])


def fake_stamp():
    LOG.append(["stamp"])
    return SET["stamp"]


def fake_read(path):
    LOG.append(["read", path.name])
    return SET["base"] if path is BASE_PATH else SET["user"]


brands.logger = FakeLogger
brands._stamp = fake_stamp
brands._read = fake_read
brands._DEFAULTS_PATH = BASE_PATH
brands._USER_PATH = USER_PATH


def ser(o):
    if isinstance(o, re.Pattern):
        return {"re": o.pattern}
    if isinstance(o, tuple):
        return {"tuple": [ser(x) for x in o]}
    if isinstance(o, (set, frozenset)):
        return {"set": sorted(ser(x) if not isinstance(x, str) else x for x in o)}
    if isinstance(o, dict):
        return {"dict": [[k, ser(v)] for k, v in o.items()]}
    if isinstance(o, list):
        return [ser(x) for x in o]
    return o


WORDS = ["Apple", "Shelly", "TP-Link", "ab", "AG", "Beijing", "Chengdu", "Xiaomi", "PHONE", "bridge", "Hue", "Ünï"]
PATTERNS = [r"\bshelly", r"^esp", "ios|mac", r"(", r"[a-", r"\d+", "apple[- ]?tv", ""]
GOOD = [r"\bshelly", r"^esp", "ios|mac", r"\d+", "apple[- ]?tv"]


def pairs(good_only=False):
    if rng.random() < 0.3:
        return pick([[], None]) if not good_only else []
    return [[pick(GOOD if good_only else PATTERNS), pick(["Apple", "Shelly", "Acme", "X"])] for _ in range(rng.randrange(0, 4))]


def alias_pairs():
    return [[pick(WORDS + ["flex", "FLEX"]), pick(["Apple", "Acme", "Zed"])] for _ in range(rng.randrange(0, 4))]


def ui_rule():
    r = rng.random()
    if r < 0.15:
        return pick([None, "x", 5, [], {"kind": "name"}, {"kind": "bad", "text": "t", "brand": "b"}, {"kind": "name", "text": 5, "brand": "b"}, {"kind": "name", "text": " ", "brand": "b"},
                     {"kind": "name", "text": "t", "brand": "  "}, {"kind": "name", "text": "t", "brand": None}])
    d = {"kind": pick(["vendor", "name", "software"]), "text": pick([" Foo.Bar ", "Hue (v2)", "ACME", "a+b", "x"]), "brand": pick(["Philips", " Acme ", "Z"])}
    if rng.random() < 0.7:
        d["id"] = pick(["r1", "r2", 3])
    return d


def make_file(is_user, weird):
    f = {}
    if rng.random() < 0.7:
        f["rules"] = pick([[ui_rule() for _ in range(rng.randrange(0, 4))], [ui_rule()], "notalist", None, {}]) if is_user else None
        if f["rules"] is None:
            del f["rules"]
    if rng.random() < 0.7:
        f["aliases"] = alias_pairs()
    for key in ("name_hints", "software_hints", "battery_hints"):
        if rng.random() < 0.7:
            f[key] = pairs(good_only=not weird)
    if rng.random() < 0.6:
        f["os_family_brand"] = pick([{}, {"ios": "Apple", "linux": "Tux"}, {"ios": "Mine"}])
    if rng.random() < 0.7:
        f["vendor_roles"] = {r: [pick(WORDS) for _ in range(rng.randrange(0, 3))] for r in pick([("component",), ("virtual", "dual"), ("component", "virtual", "dual"), ("other",), ()])}
    if rng.random() < 0.7:
        f["model_hints"] = {k: [pick(GOOD if not weird else PATTERNS) for _ in range(rng.randrange(0, 3))] for k in pick([("fixed",), ("mobile", "laptop"), ("fixed", "mobile", "laptop"), ("zzz",)])}
    for key in ("bridge_software", "phone_only_brands", "strip_words", "strip_leading_places"):
        if rng.random() < 0.7:
            f[key] = [pick(WORDS) for _ in range(rng.randrange(0, 4))]
    if weird and rng.random() < 0.5:
        k = pick(["aliases", "vendor_roles", "model_hints", "strip_words", "bridge_software", "os_family_brand"])
        f[k] = pick([None, 5, "str"])
    return f


out = []
for _ in range(N):
    weird = rng.random() < 0.12
    SET["base"], SET["user"] = make_file(False, weird), make_file(True, weird)
    if rng.random() < 0.05:
        SET["user"] = {}
    stamp = pick([(1.0, 2.0), (3.0, None), (None, None)])
    SET["stamp"] = stamp
    state = pick(["empty", "hit", "hit", "norules", "other"])
    brands._cache.clear()
    if state == "empty":
        brands._cache.update(stamp=None, rules=None)
    elif state == "hit":
        brands._cache.update(stamp=stamp, rules=SENTINEL)
    elif state == "norules":
        brands._cache.update(stamp=stamp, rules=None)
    else:
        brands._cache.update(stamp=(9.0, 9.0), rules=SENTINEL)
    LOG.clear()
    res = []
    for _ in range(2):
        try:
            res.append(ser(brands._rules()))
        except Exception as exc:
            res.append(["EXC", type(exc).__name__])
    same_obj = brands._cache["rules"] is SENTINEL
    out.append({"state": state, "res": res, "cache_stamp": brands._cache["stamp"], "cache_has_rules": brands._cache["rules"] is not None, "sentinel": same_obj, "log": list(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]      # key order matters: no sort_keys


mine = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:12], default=str))}
if os.environ.get("BRANDS_RULES_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i], default=str)[:900])
assert mine["sample"] == want["sample"]
built = [o for o in out if isinstance(o["res"][0], dict)]
exc = [o for o in out if isinstance(o["res"][0], list) and o["res"][0][:1] == ["EXC"]]
real = [o for o in built if o["res"][0] != SER_SENTINEL]
assert len(built) > 1500 and len(exc) > 30, (len(built), len(exc))
assert sum(1 for o in out if o["state"] == "hit" and o["res"][0] == SER_SENTINEL) > 800 and sum(1 for o in out if o["state"] == "other" and o["res"][0] != SER_SENTINEL) > 200
assert sum(1 for o in out if o["state"] == "norules" and o["log"][1:3] == [["read", "base_brands.json"], ["read", "user_brands.json"]]) > 200
assert sum(1 for o in built if o["res"][0] == o["res"][1]) > 1400 and sum(1 for o in out if any(l[0] == "warning" for l in o["log"])) > 50
assert any(len(dict(o["res"][0]["dict"])["aliases"]["tuple"]) > 4 for o in real) and any(dict(o["res"][0]["dict"])["strip_words"]["set"] for o in real)
assert any(dict(o["res"][0]["dict"])["places"]["set"] and dict(o["res"][0]["dict"])["phone_only"]["tuple"] for o in real)
assert any(dict(o["res"][0]["dict"])["os_family_brand"]["dict"] for o in real) and any(dict(o["res"][0]["dict"])["name_hints"]["tuple"] for o in real)
assert any(any(v["tuple"] for _, v in dict(o["res"][0]["dict"])["model_hints"]["dict"]) for o in real)
assert any(any(v["tuple"] for _, v in dict(o["res"][0]["dict"])["vendor_roles"]["dict"]) for o in real)
print("TUTTO OK")
