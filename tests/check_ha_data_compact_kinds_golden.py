"""Golden-master test of ha_data.compact_device and ha_data._kinds. compact_device runs with its collaborators (brand logo, effective_type, icon_for, _signal, i18n, identity_shift) replaced
by in-memory fakes that record every call; _kinds runs with a fake file reader (the content of device_kinds.json: valid, broken, missing key, odd entries) and the module cache reset in every
case, and is called twice to check the cache. 3000 generated cases must give exactly the same result (key ORDER included, or the exception) AND the same ordered calls as the code before the
functions were split. tests/golden/ha_data_compact_kinds.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  HA_DATA_GOLDEN_UPDATE=1 python tests/check_ha_data_compact_kinds_golden.py"""
import hashlib
import json
import os
import random
import sys
import tempfile
import types
import zlib
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import datafile  # noqa: E402
from app.ha import ha_data, ha_type_evidence  # noqa: E402

REAL_DATA_DIR = datafile.DATA_DIR
GOLDEN = Path(__file__).parent / "golden" / "ha_data_compact_kinds.json"
N = 3000
rng = random.Random(4545)
LOG: list = []
CASE = [0]
SET: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


def h(*parts):
    return zlib.crc32(repr((CASE[0],) + parts).encode())


def ser(o):
    if isinstance(o, (set, frozenset)):
        return ["__set__"] + sorted(ser(x) for x in o)
    if isinstance(o, dict):
        return {str(k): ser(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [ser(x) for x in o]
    return o


# ---------------------------------------------------------------- fakes for compact_device
def fake_logo_for(brand):
    LOG.append(["logo_for", repr(brand)])
    return [None, {}, {"id": "acme", "color": "#fff"}, {"id": "zeta"}, 0, {"id": "", "color": ""}][h("logo", repr(brand)) % 6]


def fake_effective_type(device, cfg):
    LOG.append(["effective_type", repr(device), repr(cfg)])
    return [None, "lamp", "pc", ""][h("et", repr(device.get("id"))) % 4]


def fake_icon_for(device, adapter, t):
    LOG.append(["icon_for", repr(device.get("id")), repr(adapter), repr(t)])
    return ["mdi:a", None, "mdi:b"][h("icon", repr(adapter), repr(t)) % 3]


def fake_signal(device):
    LOG.append(["_signal", repr(device.get("id"))])
    if SET.get("signal_fails"):
        raise RuntimeError("signal")
    k = h("sig", repr(device.get("id"))) % 7
    return None if k == 0 else ({} if k == 1 else {"sig": k})


def fake_t(key, *a, **k):
    LOG.append(["i18n.t", key])
    return "T:" + key


def fake_t_or(key, default):
    LOG.append(["i18n.t_or", key, repr(default)])
    return ("L:" + key) if h("tor", key) % 2 else default


def fake_attrs_for(did, tr):
    LOG.append(["attrs_for", repr(did), "t" if tr is fake_t else repr(tr)])
    return [{"key": "shift", "id": did}] if h("sh", repr(did)) % 2 else []


ha_data.brand_logo = types.SimpleNamespace(logo_for=fake_logo_for)
ha_data.effective_type = fake_effective_type
ha_data.icon_for = fake_icon_for
ha_data._signal = fake_signal
ha_data.i18n = types.SimpleNamespace(t=fake_t, t_or=fake_t_or)
ha_data.identity_shift = types.SimpleNamespace(attrs_for=fake_attrs_for)

SCALARS = [None, "", 0, 1, "x", "acme", 12.5, True, False]


def make_device():
    d = {}
    if rng.random() < 0.96:
        d["id"] = pick(["d1", "d2", "d3", 7])
    for k in ("name", "ip", "port", "mac", "vendor", "vendor_role", "brand", "brand_source", "brand_confidence", "brand_evidence", "brand_declared", "battery", "battery_source",
              "is_mobile", "online", "last_seen", "uptime", "latency_ms", "latency_color", "url", "scanned_at", "web_open", "deep_empty_at"):
        if rng.random() < 0.6:
            d[k] = pick(SCALARS + ["10.0.0.1", "aa:bb"])
    if rng.random() < 0.7:
        d["scanned_ports"] = pick([None, [], [{"label": "http", "category": "web", "confirmed": 1}, {"label": None}, {}, {"category": "", "confirmed": 0}]])
    r = rng.random()
    if r < 0.6:
        d["extra"] = pick([None, {}, {"title": "Hi", "vendor": "V", "brand": "B", "model": "M", "fw": 0, "x": None, "y": "", "z": ["l"], "t2": 3.5},
                           {"title": None, "model": "", "ssid": "net"}, {"only": 1}])
    elif r < 0.62:
        d["extra"] = pick([[1], "str", 5])
    return d


def make_cfg():
    r = rng.random()
    if r < 0.2:
        return pick([None, {}])
    c = {}
    for k in ("mobile", "name_source", "wol_ok", "ha_share", "type_user", "brand_user", "focus", "focus_note", "adapter"):
        if rng.random() < 0.5:
            c[k] = pick(SCALARS + ["note"])
    return c


def run_compact():
    SET["signal_fails"] = rng.random() < 0.05
    device, cfg = make_device(), make_cfg()
    args = (device,) if rng.random() < 0.3 else (device, cfg)
    LOG.clear()
    try:
        res = ha_data.compact_device(*args)
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    return {"res": res, "keys": list(res) if isinstance(res, dict) else None, "log": list(LOG)}


# ---------------------------------------------------------------- _kinds
class FakePath:
    def __init__(self, *a):
        self.parts = list(a)

    @property
    def name(self):
        return self.parts[-1]

    def resolve(self):
        return self

    @property
    def parent(self):
        return self

    def __truediv__(self, other):
        return FakePath(*self.parts, other)

    def read_text(self, encoding=None):
        LOG.append(["read_text", self.parts[1:], encoding])
        mode = SET["file"]
        if mode == "oserror":
            raise OSError("no file")
        return mode


def kind_entry():
    k = {}
    for key, opts in (("id", ["lamp", "cam", "boiler", "tv"]), ("group", ["climate", "appliance", "energy", "security", "cover", "water", "pc", "media", "iot", "weird"]),
                      ("icon", ["mdi:x", "", "mdi:y"])):
        if rng.random() < 0.97:
            k[key] = pick(opts)
    if rng.random() < 0.6:
        k["tokens"] = pick([None, [], ["bulb", "led"], ["x"]])
    if rng.random() < 0.8:
        k["words"] = pick([None, [], ["Light", "smart plug", "thermostat", "wi-fi", "abcdefg", "abcdefgh", "LED"], ["pump", "Heater"], ["a b", "ab"], ["x"] * 2, ["Thermostat"],
                           ["ABCDEFG", "sensor"]]) if rng.random() < 0.97 else [5]
    if rng.random() < 0.5:
        k["w"] = pick([1, 2, 3, "4", 2.9, None, "x", 0])
    for key in ("mdns", "upnp", "brands"):
        if rng.random() < 0.4:
            k[key] = pick([None, [], ["a", "b"], ["a", "a"]])
    if rng.random() < 0.4:
        k["product"] = pick([None, 0, 1, True, False, "x", []])
    return k


def kinds_text():
    r = rng.random()
    if r < 0.05:
        return "oserror"
    if r < 0.1:
        return "{broken"
    if r < 0.15:
        return json.dumps({"other": []})
    if r < 0.17:
        return json.dumps({"kinds": None})
    if r < 0.19:
        return json.dumps({"kinds": {"a": 1}})
    if r < 0.21:
        return json.dumps([])
    return json.dumps({"kinds": [kind_entry() for _ in range(rng.randrange(0, 5))]})


def run_kinds():
    SET["file"] = kinds_text()
    ha_type_evidence._kinds_cache = None
    ha_data.Path = FakePath
    datafile.DATA_DIR = FakePath("x") / "data"      # the reader of the kinds joins its file name to this folder
    LOG.clear()
    res, again = [], []
    for slot in (res, again):
        try:
            v = ha_data._kinds()
            slot.append(ser(v))
            slot.append("is-cache" if v is ha_type_evidence._kinds_cache else "not-cache")
        except Exception as exc:
            slot.extend([["EXC", type(exc).__name__], "exc"])
    return {"res": res, "same": ("identical" if res == again else "different"), "cache_is_none": ha_type_evidence._kinds_cache is None, "log": list(LOG)}


out = []
for i in range(N):
    CASE[0] = i
    out.append(["compact", run_compact()] if i % 2 == 0 else ["kinds", run_kinds()])
ha_data.Path = Path
datafile.DATA_DIR = REAL_DATA_DIR


def digest(x):
    return hashlib.sha1(json.dumps(x, default=str).encode()).hexdigest()[:20]      # key order matters: no sort_keys


mine = {"digests": [digest(o) for o in out], "sample": json.loads(json.dumps(out[:24], default=str))}
if os.environ.get("HA_DATA_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i], default=str)[:800])
assert mine["sample"] == want["sample"]

comp = [o[1] for o in out if o[0] == "compact"]
kin = [o[1] for o in out if o[0] == "kinds"]
assert sum(1 for c in comp if c["keys"]) > 1000 and sum(1 for c in comp if c["keys"] is None) > 20
assert all(c["keys"][0] == "id" for c in comp if c["keys"]) and any(c["keys"] and len(c["keys"]) == 40 for c in comp)
assert sum(1 for c in comp if c["keys"] and c["res"]["attrs"]) > 500 and sum(1 for c in comp if c["keys"] and c["res"]["ports"]) > 150
assert {c["res"]["mobile_mode"] for c in comp if c["keys"]} == {"auto", "yes", "no"}
assert any(c["res"]["logo"] == "acme" for c in comp if c["keys"]) and any(c["res"]["logo"] == {} for c in comp if c["keys"])
assert any(c["res"]["last_seen"] is None for c in comp if c["keys"]) and any(c["res"]["last_seen"] for c in comp if c["keys"])
assert any(c["log"] and c["res"][:1] == ["EXC"] and len(c["log"]) > 2 for c in comp if c["keys"] is None)
ok = [k for k in kin if k["res"][1] == "is-cache"]
assert len(ok) > 600 and sum(1 for k in kin if k["cache_is_none"]) > 20
assert sum(1 for k in ok if k["res"][0] == []) > 20 and sum(1 for k in ok if k["res"][0]) > 400 and sum(1 for k in kin if k["same"] == "identical") > 600
assert any(e["group"] == "iot" for k in ok for e in k["res"][0]) and any(e["subs"] for k in ok for e in k["res"][0]) and any(e["toks"][0] == "__set__" and len(e["toks"]) > 3 for k in ok for e in k["res"][0])
assert sum(1 for k in kin if len(k["log"]) == 1) > 600 and sum(1 for k in kin if len(k["log"]) == 2) > 20
print("TUTTO OK")
