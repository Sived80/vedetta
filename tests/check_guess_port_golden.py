"""Golden-master test of scan_web._guess_port (the most likely web port of a device, for the button and the pop-up): 3500 generated lists of ports - a port that answered over
HTTP with a title or a body of some size, 80 and 443 among them or not, several confirmed ports with equal and different sizes, services recognised as web, ephemeral ports,
no evidence at all - must give exactly the port stored in tests/golden/guess_port.json, written from the code as it was before the function was split.
Regenerate only on purpose:  GUESSPORT_GOLDEN_UPDATE=1 python tests/check_guess_port_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_web  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "guess_port.json"
N = 3500
rng = random.Random(80808)
PORTS = [22, 80, 443, 1884, 3000, 4357, 8080, 8086, 8123, 8200, 9000, 49151, 49152, 50000, 61208]
SERVICES = ["http", "https", "http-alt", "www", "ssh", "unknown", "x11", None, "upnp", "sun-answerbook"]
SIZES = [None, 0, 19, 1100, 4357, 8900, 63000, 63000]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def entry():
    e = {"port": pick(PORTS), "service": pick(SERVICES)}
    if rng.random() < 0.4:
        e["has_http_title"] = pick([True, False])
    size = pick(SIZES)
    if size is not None or rng.random() < 0.3:
        e["http_body_size"] = size
    return e


out = []
for _ in range(N):
    ports = [entry() for _ in range(rng.randrange(0, 7))]
    try:
        out.append([ports, scan_web._guess_port(ports)])
    except Exception as exc:
        out.append([ports, {"exception": type(exc).__name__}])
out = json.loads(json.dumps(out, sort_keys=True))
if os.environ.get("GUESSPORT_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [r[1] for r in out]
assert sum(1 for r in res if isinstance(r, dict)) < N / 8, "too many exceptions"
assert len({r for r in res if isinstance(r, int)}) >= 8 and sum(1 for r in res if r == 80) > 300 and sum(1 for r in res if r not in (80, 443) and isinstance(r, int)) > 500, "scenarios too uniform"
print("TUTTO OK")
