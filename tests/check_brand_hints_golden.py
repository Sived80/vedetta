"""Golden-master test of the three ways to find a hint in a list of texts in recognition/brands.py: match_model (the class of the announced model), battery_hint (the battery of a fixed device) and
resolve (the brand, from the OS family, the names, the web text, the declared manufacturers and the MAC manufacturer; its name and software hints are the same search). 4000 generated cases each - texts made of
the words of the real rules and of the brand names (several words, any case, with digits), plus None, empty and blank texts, lists of one or many texts, every order - with the real rules of the data
files must give exactly the results stored in tests/golden/brand_hints.json (a short digest per case plus a readable sample), written from the code as it was before the three searches shared one.
Regenerate only on purpose:  BRAND_HINTS_GOLDEN_UPDATE=1 python tests/check_brand_hints_golden.py"""
import hashlib
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import brands  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "brand_hints.json"
N = 4000
rng = random.Random(31415)
R = brands._rules()


def pick(seq):
    return seq[rng.randrange(len(seq))]


words = set()
for key in ("name_hints", "software_hints", "battery_hints"):
    for pattern, _answer in R[key]:
        words |= set(re.findall(r"[a-z][a-z0-9]{2,}", pattern.pattern.lower()))
for pats in R["model_hints"].values():
    for pattern in pats:
        words |= set(re.findall(r"[a-z][a-z0-9]{2,}", pattern.pattern.lower()))
words |= {a[0].lower() for a in R["aliases"]} | {a[1].lower() for a in R["aliases"]}
WORDS = sorted(words) + ["iphone15", "macmini9", "macbookpro18", "xx", "box"]
OUIS = [None, "", "Sony", "Apple", "Acme", "Espressif", "Tp-Link", "Intel"] + [v for vs in R["vendor_roles"].values() for v in vs][:8]
OS = [None, "", "linux"] + sorted(R["os_family_brand"])


def text():
    kind = rng.random()
    if kind < 0.08:
        return pick([None, "", "   ", "\t"])
    t = " ".join(pick(WORDS) for _ in range(rng.randrange(1, 4)))
    t = pick([t, t.upper(), t.title(), t + str(rng.randrange(0, 20)), t.replace(" ", "-")])
    return t


def texts():
    return [text() for _ in range(pick([0, 1, 1, 2, 3, 5]))]


def dumps(x):
    return json.dumps(x, sort_keys=True, default=repr)


cases, stats = [], {"model": 0, "battery": 0, "resolve_name": 0, "resolve_web": 0, "resolve_other": 0, "resolve_none": 0}
for _ in range(N):
    a = texts()
    out = {"model_texts": a, "model": brands.match_model(a)}
    b = texts()
    out.update({"battery_texts": b, "battery": brands.battery_hint(b)})
    names = pick([[], texts(), texts(), texts()])
    kw = dict(names=names, upnp_manufacturer=pick([None, "", "Sony", " acme "] + [pick(WORDS)]), declared=pick([(), ["Sony"], (pick(WORDS), None, ""), [pick(WORDS)]]),
              web_text=pick([None, "", text(), text()]), os_family=pick(OS), is_gateway=pick([True, False]))
    oui = pick(OUIS)
    out.update({"resolve_args": [oui, kw], "resolve": brands.resolve(oui, **kw)})
    cases.append(out)
    stats["model"] += out["model"] is not None
    stats["battery"] += out["battery"] is not None
    src = out["resolve"]["source"]
    stats["resolve_name"] += src == "name"
    stats["resolve_web"] += src == "web"
    stats["resolve_other"] += src in ("dhcp", "declared", "oui")
    stats["resolve_none"] += src is None
digests = [hashlib.sha1(dumps(c).encode("utf-8")).hexdigest()[:10] for c in cases]
out = {"digests": digests, "sample": json.loads(dumps(cases[:10]))}
if os.environ.get("BRAND_HINTS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(out, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print("golden written", stats)
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
bad = [i for i, (x, y) in enumerate(zip(digests, want["digests"])) if x != y]
assert not bad and len(digests) == len(want["digests"]), "brands hints differ from the golden at cases %s" % bad[:10]
assert out["sample"] == want["sample"]
for key, low in (("model", 200), ("battery", 100), ("resolve_name", 200), ("resolve_web", 100), ("resolve_other", 200), ("resolve_none", 200)):
    assert stats[key] >= low, ("the generator no longer reaches this case", key, stats)
print("TUTTO OK", stats)
