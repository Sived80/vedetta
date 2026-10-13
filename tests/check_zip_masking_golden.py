"""Golden-master test of export_zip._add_board_devices, _mask_structured and _put_data_files, with the collaborators replaced by in-memory ones that record every call
(anonymizer, registries, DHCP and mDNS tables, ha_data, the zip writer): generated inputs must give exactly the same result (or exception) AND the same ordered calls as the code
before the functions were split. tests/golden/zip_masking.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  ZIP_MASKING_GOLDEN_UPDATE=1 python tests/check_zip_masking_golden.py"""
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
from app.export import export_zip as ez  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "zip_masking.json"
N = 3000
rng = random.Random(11011)
LOG: list = []
CASE = [0]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def h(*parts):
    return zlib.crc32(repr((CASE[0],) + parts).encode())


class FakeAnon:
    def __getattr__(self, name):
        def call(*a, **k):
            LOG.append([name, repr(a), repr(sorted(k.items()))])
            if name == "data":
                return a[0] if (a[0] is None or h("id", repr(a[0])) % 3 == 0) else {"m": a[0]}
            if name == "leaks_data":
                return "LEAK" in json.dumps(a[0], default=str)
        return call


# ---------------------------------------------------------------- _add_board_devices
class Tbl(dict):
    pass


def setup_registries(devices):
    dhcp = types.SimpleNamespace(seen={})
    mdns = types.SimpleNamespace(by_mac={})
    reg_state = {"by_mac": {}}
    for _ in range(rng.randrange(0, 4)):
        dhcp.seen[pick(["aa:01", "aa:02", "", "bb:03"])] = pick([{"hostname": "h1"}, {}, None, {"hostname": ""}, {"hostname": None}])
    for _ in range(rng.randrange(0, 3)):
        mdns.by_mac[pick(["aa:01", "cc:09", ""])] = {}
    for _ in range(rng.randrange(0, 3)):
        reg_state["by_mac"][pick(["aa:02", "dd:10", None])] = {}

    def lookup_reg(mac, ip):
        LOG.append(["reg.lookup", repr(mac), repr(ip)])
        k = h("reg", mac, ip) % 5
        return [None, {}, {"area": "kitchen", "name": "regname"}, {"area": None, "name": None}, {"name": "r2"}][k]

    def lookup_mdns(mac, ip):
        LOG.append(["mdns.lookup", repr(mac), repr(ip)])
        k = h("mdns", mac, ip) % 4
        return [None, {}, {"name": "mdnsname"}, {"name": None}][k]

    def effective_type(d, other):
        LOG.append(["effective_type", repr(d), repr(other)])
        k = h("et", repr(d)) % 4
        if k == 0:
            raise RuntimeError("boom")
        return [None, "", "camera", "lamp"][k]

    def icon_for(d, other, hint):
        LOG.append(["icon_for", repr(d), repr(other), repr(hint)])
        k = h("ic", repr(d)) % 4
        if k == 0:
            raise ValueError("boom")
        return [None, "", "mdi:cam", "mdi:lamp"][k]

    dhcp.lookup = None
    ez.dhcp = dhcp
    ez.mdns_listener = types.SimpleNamespace(by_mac=mdns.by_mac, lookup=lookup_mdns)
    ez.ha_registry = types.SimpleNamespace(_state=reg_state, lookup=lookup_reg)
    ez.ha_data = types.SimpleNamespace(effective_type=effective_type, icon_for=icon_for)


def dev():
    d = {}
    for k, opts in (("ip", [None, "", "10.0.0.1", "10.0.0.2"]), ("mac", [None, "", "aa:01", "AA:02", "bb:03", "cc:09"]),
                    ("name", [None, "", "10.0.0.1", "10.0.0.2", "lamp", "cam"]), ("brand", [None, "", "acme", "zeta"])):
        if rng.random() < 0.85:
            d[k] = pick(opts)
    if rng.random() < 0.3:
        d["x"] = rng.randrange(5)
    return d


def run_board():
    devices = [dev() for _ in range(rng.randrange(0, 5))]
    setup_registries(devices)
    LOG.clear()
    try:
        res = ez._add_board_devices(FakeAnon(), devices)
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    return {"res": res, "log": list(LOG)}


# ---------------------------------------------------------------- _mask_structured
def jvalue():
    return pick([{"a": 1}, {"a": "LEAK"}, [1, 2], None, "text", 5, {"k": ["x", {"y": "LEAK"}]}, {}, [], "LEAK", True])


def jtext():
    k = rng.randrange(7)
    if k == 0:
        return json.dumps(jvalue())
    if k == 1:
        return pick(["", "{", "not json", "   ", "{'a': 1}"])
    return json.dumps(jvalue(), indent=1)


def jltext():
    lines = []
    for _ in range(rng.randrange(0, 6)):
        lines.append(pick([json.dumps(jvalue()), json.dumps(jvalue()), "", "  ", "\t", "null", " null ", "1", " []", "[]", "0", "\"\"", "{bad", json.dumps({"z": "LEAK"}), "[1]"]))
    return pick(["\n", "\n", ""]).join(lines) if rng.random() < 0.7 else "\n".join(lines) + pick(["", "\n"])


def run_mask():
    name = pick(["a.json", "b.jsonl", "c.txt", "d.json.jsonl", ".json", ".jsonl", "", "e.JSON", "f.jsonl.bak", "g.log", "ajson", "ajsonl", "json", "jsonl"])
    text = jltext() if rng.random() < 0.5 else jtext()
    LOG.clear()
    try:
        res = ez._mask_structured(name, text, FakeAnon())
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    return {"name": name, "res": res, "log": list(LOG)}


# ---------------------------------------------------------------- _put_data_files
class FakeZip:
    def __init__(self):
        self.manifest = {"notes": []}
        self.puts = []
        self.fail = None

    def put(self, name, content, text=True):
        if self.fail and self.fail in name:
            raise RuntimeError("put failed")
        self.puts.append([name, content if isinstance(content, str) else ("bytes", hashlib.sha1(content).hexdigest(), len(content))])


BIG = 2 * 1024 * 1024


def make_dir():
    d = Path(tempfile.mkdtemp())
    names = ["a.json", "b.json", "c.log", "d.jsonl", "e.txt", "vedetta.db", "vedetta.db-wal", ez.MAPPING_FILE, "my_key.json", "Token.log", "secret.txt", "pass.json",
             "user_lang.json", "plain", "x.JSON", "sub.json", "api-keys.txt", "k.jsonl", "bad.json", "bin.json"]
    for nm in rng.sample(names, rng.randrange(0, 9)):
        p = d / nm
        if nm == "sub.json":
            p.mkdir()
            continue
        k = rng.randrange(6)
        if nm == "bad.json" or k == 0:
            data = pick([b"{bad", b"", b"\xff\xfe\x00"]) if nm.endswith(".json") else b"abc"
        elif nm.endswith(".json") or nm == "my_key.json":
            data = json.dumps(pick([{"token": "t", "n": 1}, {"a": {"password": "p", "b": [{"secret_x": "s", "c": 2}, {"key": ""}]}}, [1, {"user_key": 0}], 5, {"k": None}]),
                              indent=pick([None, 1])).encode()
        elif nm.endswith((".log", ".jsonl")):
            line = b'{"line": "%d"}\n'
            data = b"".join(line % i for i in range(pick([1, 5, 150000]))) if rng.random() < 0.3 else b"first\nsecond\nthird\n"
        else:
            data = pick([b"hello", b"\x00\x01", b""])
        p.write_bytes(data)
    return d


def run_files():
    z = FakeZip()
    r = rng.random()
    if r < 0.1:
        d = Path(tempfile.mkdtemp()) / "missing"
    else:
        d = make_dir()
    if rng.random() < 0.15:
        z.fail = pick(["a.json", "c.log", "e.txt", "plain", "d.jsonl"])
    try:
        res = ez._put_data_files(z, d)
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    return {"res": res, "puts": z.puts, "notes": z.manifest["notes"]}


# ---------------------------------------------------------------- driver
out = []
for i in range(N):
    CASE[0] = i
    kind = i % 3
    if kind == 0:
        out.append(["board", run_board()])
    elif kind == 1:
        out.append(["mask", run_mask()])
    else:
        out.append(["files", run_files()])


def digest(x):
    return hashlib.sha1(json.dumps(x, sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:20]


mine = {"digests": [digest(o) for o in out], "sample": [o for o in out[:40]]}
mine = json.loads(json.dumps(mine, sort_keys=True))
if os.environ.get("ZIP_MASKING_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i])[:600])
assert mine["sample"] == want["sample"]

board = [o[1] for o in out if o[0] == "board"]
mask = [o[1] for o in out if o[0] == "mask"]
files = [o[1] for o in out if o[0] == "files"]
assert sum(1 for b in board if any(c[0] == "add_devices" for c in b["log"])) > 900
assert any(c[0] == "icon_for" for b in board for c in b["log"]) and sum(1 for b in board if not b["log"]) < 400
assert sum(1 for m in mask if m["res"] is None) > 150 and sum(1 for m in mask if isinstance(m["res"], str)) > 150 and sum(1 for m in mask if m["res"] and m["res"][0] == "EXC") > 50
assert sum(1 for f in files if f["puts"]) > 600 and sum(1 for f in files if f["notes"]) > 100 and any(len(f["puts"]) > 3 for f in files)
assert any(p[0].startswith("data/") and p[0].endswith(".log") for f in files for p in f["puts"])
print("TUTTO OK")
