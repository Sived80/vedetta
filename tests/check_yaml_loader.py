"""devices.yaml is read several times in every cycle of the service, so it is parsed with the C parser of libyaml when this PyYAML has it (about ten times faster than the pure-Python one:
measured on real data, 187 ms against about 20 ms per reading). It must give EXACTLY the same result as the safe pure-Python loader. Checked here on 3000 generated documents - unicode names, ports,
booleans and nulls, strings that look like numbers, booleans or dates, nested lists and mappings, flow style, comments, anchors, multi-line text - and on the file as devices_config reads it;
and the loader that devices_config uses must be the C one whenever it is available (the structure, not the time, so the test does not depend on the machine)."""
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import yaml  # noqa: E402
from app.storage import devices_config  # noqa: E402

rng = random.Random(2468)
pick = lambda seq: seq[rng.randrange(len(seq))]  # noqa: E731
STRINGS = ["Salotto", "TV 4K è bella", "yes", "no", "on", "off", "null", "~", "true", "False", "1e3", "0x1f", "010", "2020-01-01", "12:30", "1_000", ".inf", "-.5", "", " lead", "trail ", "a: b", "- x", "#hash",
           "line1\nline2", "café", "日本語", "'quoted'", "\"dq\"", "!tag", "&anchor", "*alias", "{braces}", "[brackets]", "a, b", "= equals", "<<", "multi word name here", "10.0.0.5", "AA:BB:CC:DD:EE:FF"]


def value(depth=0):
    kind = rng.randrange(8 if depth < 2 else 5)
    if kind == 0:
        return pick(STRINGS)
    if kind == 1:
        return rng.randrange(-5, 70000)
    if kind == 2:
        return pick([True, False, None])
    if kind == 3:
        return round(rng.uniform(-100, 100), 3)
    if kind == 4:
        return pick(STRINGS) + str(rng.randrange(10))
    if kind == 5:
        return [value(depth + 1) for _ in range(rng.randrange(0, 4))]
    return {pick(["k", "ports", "label", "ip", "x y", "1", "true", "null"]) + str(i): value(depth + 1) for i in range(rng.randrange(0, 4))}


def device(i):
    d = {"id": "scan-10-0-0-%d" % i, "ip": "10.0.0.%d" % (i % 250), "adapter": pick(["generic", "shelly_gen1"]), "name": pick(STRINGS), "name_source": pick(["user", "mdns", None])}
    if rng.random() < 0.6:
        d["port"] = pick([80, 443, 8080])
    if rng.random() < 0.6:
        d["scan_info"] = {k: value() for k in rng.sample(["http_title", "ports", "mdns_name", "mdns_services", "tls_subject", "snmp_descr", "scanned_at", "api_fw"], rng.randrange(0, 6))}
    return d


def same(a, b):
    return json.dumps(a, sort_keys=True, default=repr) == json.dumps(b, sort_keys=True, default=repr)


# 1. documents written the way the app writes them (safe_dump), with the options it uses
for i in range(3000):
    doc = {"devices": [device(j) for j in range(rng.randrange(0, 5))]}
    text = yaml.safe_dump(doc, allow_unicode=pick([True, False]), sort_keys=False, default_flow_style=pick([None, False]))
    a, b = yaml.load(text, Loader=yaml.SafeLoader), devices_config._read_yaml(text)
    assert same(a, b) and a == b, "document %d differs between the pure-Python and the C loader:\n%s" % (i, text[:400])

# 2. documents written by hand: flow style, comments, anchors, multi-line text, tabs after values, document markers
HAND = ["devices: [{id: a, ip: 10.0.0.1, name: 'x y', port: 80}, {id: b, name: yes}]\n", "# comment\ndevices:\n  - id: a   # trailing\n    name: |\n      line one\n      line two\n    ports: [80, 443,]\n",
        "---\ndevices:\n- &d {id: a, ip: 1.2.3.4}\n- *d\n...\n", "devices:\n  - id: a\n    name: >\n      folded\n      text\n    mobile: no\n    brand: ~\n", "", "{}\n", "devices: []\n", "devices:\n", "devices: null\n",
        "devices:\n  - {id: a, n: 0o17, m: 0b11, f: 1.5e3, d: 2001-12-14, t: 2001-12-14t21:59:43.10-05:00}\n", "devices:\n - id: \"\\u00e8\\n\"\n"]
for text in HAND:
    a, b = yaml.load(text, Loader=yaml.SafeLoader), devices_config._read_yaml(text)
    assert same(a, b) and a == b, "hand-written document differs:\n" + text

# 3. the file as devices_config reads it, and the loader in use
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devs = [device(i) for i in range(30)]
devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": devs}, allow_unicode=True, sort_keys=False), encoding="utf-8")
assert devices_config.load_devices() == yaml.safe_load(devices_config.DEVICES_PATH.read_text(encoding="utf-8"))["devices"]
assert devices_config._LOADER is (yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader), "devices_config must use the C loader when this PyYAML has it"
print("TUTTO OK (C loader %s)" % ("in use" if devices_config._LOADER is getattr(yaml, "CSafeLoader", None) else "not available: pure Python"))
