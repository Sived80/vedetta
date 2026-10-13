"""Golden-master test of brands.add_rule (validation, replace-or-append of a rule, ids for the rules that lack one) and brands.resolve (product brand with source, confidence and role):
4000 generated cases for each. add_rule runs on an in-memory copy of the user file (`_read`, `_write_user` and `uuid` are replaced: the ids are a counter, so the number and the ORDER of the
id requests count too); resolve runs on a small synthetic rules table (`_rules` is replaced) with every source (dhcp, name, web, declared, oui) and every vendor role, falsy brands and
empty names included. Both must give exactly the results stored in tests/golden/brands.json, written from the code as it was before the two functions were split (the key order of
the returned dictionaries counts).
Regenerate only on purpose:  BRANDS_GOLDEN_UPDATE=1 python tests/a3_check_brands_golden.py"""
import copy
import json
import os
import random
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import brands  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "brands.json"
N = 4000
rng = random.Random(8642097)


def pick(seq):
    return seq[rng.randrange(len(seq))]


# ---------------------------------------------------------------- add_rule
KINDS = ["vendor", "name", "software"]
TEXTS = ["", " ", "a", "ab", " ab ", "AB", "x" * 80, "x" * 81, " " + "x" * 80 + " ", "Ciao", "ciao", " CIAO", None, 5]
BRANDS = ["", " ", "B", " B ", "b", "Acme", "acme", "y" * 60, "y" * 61, " " + "y" * 60, None, 7]
counter = [0]


def _uuid4():
    counter[0] += 1
    return types.SimpleNamespace(hex=("%08x" % counter[0]) + "ab" * 12)


brands.uuid = types.SimpleNamespace(uuid4=_uuid4)


def stored_rule():
    r = pick([
        {"id": "id%d" % rng.randrange(50), "kind": pick(KINDS), "text": pick(["ab", "AB", "ciao", " Ciao ", "x" * 80, "zz"]), "brand": pick(["Acme", "Old", " Pad "])},
        {"id": "", "kind": pick(KINDS), "text": pick(["ab", "ciao", "zz"]), "brand": "Old"},
        {"kind": pick(KINDS), "text": "ab", "brand": "NoId"},
        {"id": 12, "kind": pick(KINDS), "text": "ciao", "brand": "NumId"},
        {"id": "bad", "kind": "other", "text": "ab", "brand": "Old"},
        {"id": "bad", "kind": "name", "text": "  ", "brand": "Old"},
        {"id": "bad", "kind": "name", "text": "ab", "brand": ""},
        {"id": "bad", "kind": "name", "text": 5, "brand": "Old"},
        "junk", None, 3,
    ])
    return r


def initial_data():
    data = {}
    if rng.random() < 0.9:
        data["rules"] = [stored_rule() for _ in range(rng.randrange(0, 6))] if rng.random() < 0.95 else pick(["notalist", None, {"a": 1}])
    if rng.random() < 0.5:
        data["aliases"] = [["x", "X"]]
    if rng.random() < 0.3:
        data["oui_meta"] = {"n": 1}
    return data


add_out = []
add_kinds = {"replaced": 0, "appended": 0, "kind": 0, "text": 0, "brand": 0, "filled": 0, "other_exc": 0}
for _ in range(N):
    state = initial_data()
    before = copy.deepcopy(state)
    written = []
    brands._read = lambda path, state=state: copy.deepcopy(state)
    brands._write_user = lambda data, written=written: written.append(copy.deepcopy(data))
    counter[0] = 0
    kind = pick(KINDS * 5 + ["bad", None, "", "Vendor"])
    text, brand = pick(TEXTS), pick(BRANDS)
    if rng.random() < 0.7:  # often the same rule again, to reach the replacement
        kind = pick(KINDS) if rng.random() < 0.9 else kind
        text = pick(["ab", "AB", " ab ", "ciao", "CIAO", "x" * 80])
        brand = pick(["Acme", "New", " New "])
    try:
        ret = brands.add_rule(kind, text, brand)
        res = {"ret": ret, "written": written, "uuids": counter[0]}
        n_before = len(brands._valid_rules(before))
        n_after = len(ret["rules"])
        add_kinds["replaced" if n_after == n_before else "appended"] += 1
        if any(isinstance(r, dict) and not r.get("id") for r in before.get("rules", []) if isinstance(before.get("rules"), list)) and counter[0] > 1:
            add_kinds["filled"] += 1
    except Exception as exc:
        res = {"exception": type(exc).__name__, "args": [str(a) for a in exc.args], "written": written, "uuids": counter[0]}
        add_kinds[exc.args[0] if isinstance(exc, ValueError) and exc.args and exc.args[0] in ("kind", "text", "brand") else "other_exc"] += 1
    add_out.append(res)

# ---------------------------------------------------------------- resolve
RULES = {
    "os_family_brand": {"ios": "Apple", "macos": "Apple", "android": "Android", "weird": ""},
    "name_hints": [(re.compile(p), b) for p, b in [(r"ipad|iphone", "Apple"), (r"echo", "Amazon"), (r"shelly", "Shelly"), (r"nullbrand", ""), (r"tv", "TVCo")]],
    "software_hints": [(re.compile(p), b) for p, b in [(r"synology", "Synology"), (r"hass", "Home Assistant"), (r"shelly", "Shelly Web"), (r"^$", "EmptyWeb")]],
    "aliases": (("apple", "Apple"), ("tp-link", "TP-Link"), ("sonos", "Sonos"), ("acme", "Acme Corp"), ("zzempty", "")),
    "vendor_roles": {"component": ("espressif", "bouffalo"), "virtual": ("proxmox",), "dual": ("netgear", "avm")},
}
brands._rules = lambda: RULES
OUIS = [None, "", "Acme", "Espressif Systems", "Proxmox Server", "Netgear", "AVM GmbH", "Sonos", "Apple Inc"]
NAME_POOL = ["Anna's iPad", "echo-dot", "shelly1-AB12", "NULLBRAND", "tv-sala", "plain", "", None, "SHELLY"]
WEB = [None, "", "Synology DiskStation", "hass.io", "Shelly Web UI", "nothing", "SYNOLOGY"]
MANUFACTURERS = [None, "", "TP-Link Technologies", "ACME", "sonos inc", "Unknown Corp", "apple", "ZZEmpty Ltd"]
OS_FAMILIES = [None, "", "ios", "macos", "android", "weird", "linux"]

res_out = []
sources = {}
confs = {}
roles = {}
for _ in range(N):
    kwargs = dict(
        names=[pick(NAME_POOL) for _ in range(rng.randrange(0, 4))],
        upnp_manufacturer=pick(MANUFACTURERS),
        declared=pick([(), [], [pick(MANUFACTURERS)], (pick(MANUFACTURERS), pick(MANUFACTURERS))]),
        web_text=pick(WEB),
        os_family=pick(OS_FAMILIES) if rng.random() < 0.4 else None,
        is_gateway=pick([True, False]),
    )
    if rng.random() < 0.5:  # fewer signals: the weaker sources are reached more often
        kwargs["web_text"] = None if rng.random() < 0.7 else kwargs["web_text"]
        kwargs["names"] = [n for n in kwargs["names"] if n in (None, "", "plain")]
    oui = pick(OUIS)
    try:
        r = brands.resolve(oui, **kwargs)
        res_out.append(r)
        sources[r["source"]] = sources.get(r["source"], 0) + 1
        confs[r["confidence"]] = confs.get(r["confidence"], 0) + 1
        roles[r["role"]] = roles.get(r["role"], 0) + 1
    except Exception as exc:
        res_out.append({"exception": type(exc).__name__})

out = {"add_rule": add_out, "resolve": res_out}
text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("BRANDS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for part in ("add_rule", "resolve"):
    assert len(want[part]) == len(out[part]) == N
    for i, (x, y) in enumerate(zip(out[part], want[part])):
        assert json.dumps(x) == json.dumps(y), "%s case %d differs: %s" % (part, i, json.dumps([x, y])[:600])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert all(add_kinds[k] > 150 for k in ("replaced", "appended", "kind", "text", "brand", "filled")), add_kinds
assert add_kinds["other_exc"] > 0 and not any("exception" in r for r in res_out)
assert all(sources.get(s, 0) > 150 for s in ("dhcp", "name", "web", "declared", "oui", None)), sources
assert confs.get("low", 0) > 50 and confs.get("medium", 0) > 150 and confs.get("high", 0) > 500 and confs.get(None, 0) > 100, confs
assert all(roles.get(r, 0) > 100 for r in ("brand", "dual", "component", "virtual", None)), roles
assert any(r["brand"] == "" and r["source"] == "name" for r in res_out) and any(r["brand"] == "" and r["source"] == "dhcp" for r in res_out)
print("TUTTO OK")
