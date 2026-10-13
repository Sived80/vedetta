"""Golden-master test of probe._web_url (the address of the "open web interface" button): 3000 generated lists of scanned ports - pages verified or not, with and
without a scheme, the port the device was added with open or closed, web services that are only guessed or confirmed, labels without a number, no ports at all -
must give exactly the address stored in tests/golden/web_url.json, written from the code as it was before the function was split.
Regenerate only on purpose:  WEBURL_GOLDEN_UPDATE=1 python tests/check_web_url_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import probe  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "web_url.json"
N = 3000
rng = random.Random(1357)
PORTS = [80, 443, 8080, 8443, 61208, 8006, 5000, 22, 3000, 9000]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def entry() -> dict:
    n = pick(PORTS)
    e = {"label": pick([f"{n} http", f"{n} https", f"{n}/tcp web", f"{n}", f"{n} HTTPS admin", "web", "", "x80 http", "0 http"])}
    if rng.random() < 0.6:
        e["web_ui"] = pick([True, True, False])
        if e["web_ui"] and rng.random() < 0.7:
            e["web_scheme"] = pick(["http", "https", None])
    if rng.random() < 0.6:
        e["category"] = pick(["web", "web", "ssh", "other"])
    if rng.random() < 0.6:
        e["confirmed"] = pick([True, False])
    return e


def case():
    ports = [entry() for _ in range(rng.randrange(0, 7))]
    return "192.168.1.%d" % rng.randrange(1, 250), pick([80, 80, 443, 8080, 61208, 22, 5000]), ports


out = []
for _ in range(N):
    ip, port, ports = case()
    try:
        out.append([ip, port, ports, probe._web_url(ip, port, ports)])
    except Exception as exc:
        out.append([ip, port, ports, {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("WEBURL_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
urls = [r[3] for r in out]
assert not any(isinstance(u, dict) for u in urls), [u for u in urls if isinstance(u, dict)][:2]
assert sum(1 for u in urls if u.startswith("https://")) > 200 and sum(1 for u in urls if u.startswith("http://")) > 800 and len(set(urls)) > 500, "scenarios too uniform"
others = sum(1 for r in out if r[3] != "http://%s:%s" % (r[0], r[1]))
assert others > 600, others
print("TUTTO OK")
