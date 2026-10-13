"""Golden-master test of Anonymizer.leak_items (what is still readable in masked text): 500 generated texts mixing every kind of leak and of harmless
look-alike (addresses, MACs in several forms, e-mails, IPv6, domains, secrets, known names and areas, placeholders) must give exactly the list (value and
ORDER) stored in tests/golden/leak_items.json, written from the code as it was before the function was split.
Regenerate only on purpose:  LEAK_GOLDEN_UPDATE=1 python tests/check_leak_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "leak_items.json"
N = 500
rng = random.Random(31337)
PIECES = [
    "192.168.1.20", "192.168.300.4", "172.20.3.4", "172.40.3.4", "10.1.2.3", "8.8.8.8", "93.184.216.34", "1.2.3.4", "224.0.0.251", "203.0.113.9", "127.0.0.1",
    "172-31-1-1", "172-32-1-1", "172_16_0_9", "192-168-4-4", "192-169-4-4", "172-15-1-1", "172.31.1.1", "172.32.1.1", "version 5.6.7.8", "v 9.9.9.9", "f0:18:98:aa:bb:cc", "F0-18-98-AA-BB-CC", "f01898aabbcc", "98aabbcc", "00:11:22:33:44:55", "mario@example.com",
    "x@masked.invalid", "fe80::1", "2001:db8::5", "::1", "nas.example.org", "home.local", "github.com", "token=abc123", "password: hunter2", "password=***",
    "https://user:pw@host/x", "https://host/x", "Anna's iPhone", "Cucina", "Salotto", "anna", "device-1", "net-2", "plain words here", "{\"a\": 1}", "\n", ",",
]
a = anonymize.Anonymizer()
a.add_ip("192.168.1.20"); a.add_mac("f0:18:98:aa:bb:cc"); a.add_public_ip("93.184.216.34")
a.add_device(["Anna's iPhone", "Mario"], "phone"); a.add_names(["Salotto"], None); a.add_areas(["Cucina"]) if hasattr(a, "add_areas") else None
b = anonymize.Anonymizer()                           # nothing registered: only the pattern based kinds
out = []
for i in range(N):
    text = " ".join(rng.choice(PIECES) for _ in range(rng.randrange(1, 9)))
    an = a if i % 3 else b
    try:
        out.append(an.leak_items(text))
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out))
if os.environ.get("LEAK_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
kinds = {k for o in out if isinstance(o, list) for k, _ in o}
assert len(kinds) >= 8, kinds
assert not any(isinstance(o, dict) for o in out)
print("TUTTO OK", sorted(kinds))
