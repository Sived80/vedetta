"""Every message the app writes in its log and journal goes through the masking and must come out clean: the export refuses
a file the safety check does not like, so a message nobody thought of could stop it for a stranger. The messages are found
in the source (logger.* and emit_alert calls), filled with awkward values (multicast groups, addresses, names, errors) and
checked: after the masking the safety check must find nothing, and the personal values must be gone."""
import ast
import itertools
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
from app import anonymize  # noqa: E402

# --- the messages: every string given to logger.<level>(...) or emit_alert(...), plus the texts of the journal
templates = set()
for path in sorted((ROOT / "app").rglob("*.py")):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            first = node.args[0]
            if name in ("debug", "info", "warning", "error", "exception", "critical", "emit_alert") and isinstance(first, ast.Constant) and isinstance(first.value, str):
                templates.add(first.value)
            elif name in ("debug", "info", "warning", "error") and isinstance(first, ast.JoinedStr):
                templates.add("".join(p.value if isinstance(p, ast.Constant) else "%s" for p in first.values))
for lang in ("en", "it"):
    for f in (ROOT / "app" / "locales" / lang).glob("*.json"):
        for key, text in json.loads(f.read_text(encoding="utf-8")).items():
            if key.startswith(("alert.", "log.", "ha.logbook.", "journal.")):
                templates.add(re.sub(r"\{\w+\}", "%s", text))
assert len(templates) > 80, len(templates)

SAMPLES = [
    "192.168.1.5", "(AA:BB:CC:00:11:22)", "239.255.255.250", "224.0.0.251", "255.255.255.255", "0.0.0.0", "127.0.0.1", "169.254.7.7", "100.64.1.1",
    "Anna's iPhone", "giulia-ipad", "Salotto TV Samsung", "10.0.0.1 > 81.174.0.21 > 1.1.1.1", "93.184.216.34", "fe80::1%eth0", "ff02::c",
    "http://192.168.1.5:80/path?x=1", "scan-192-168-1-5", "host-172-20-4-7", "nmap 7.94", "lighttpd/1.4.55", "v10.0.1.2",
    "HTTPConnectionPool(host='192.168.1.5', port=80): Max retries exceeded", "OSError(113, 'No route to host')", "[Errno 111] Connection refused",
    "/data/vedetta.db", "mqtt://core-mosquitto:1883", "Europe/Rome", "2026-10-06T10:00:00+02:00", "ValueError('x')", "1.2.3", "42", "12.5",
]
FILL = re.compile(r"%[-#0 +]*\d*(?:\.\d+)?[sdrfxi]|\{\w*\}")
NUMBERS = ["0", "7", "42", "12.5", "300"]

a = anonymize.Anonymizer()
for ip in ("192.168.1.5", "10.0.0.1", "172.20.4.7"):
    a.add_ip(ip)
a.add_mac("aa:bb:cc:00:11:22")
a.add_device(["Anna's iPhone", "giulia-ipad", "Salotto TV Samsung"], "phone")
a.add_public_ip("93.184.216.34")

checked = 0
for template in sorted(templates):
    n = len(FILL.findall(template))
    if n == 0:
        combos = [()]
    elif n <= 3:
        combos = itertools.islice(itertools.product(SAMPLES, repeat=n), 4000) if n == 3 else itertools.product(SAMPLES, repeat=n)
    else:
        combos = [tuple(SAMPLES[(i + k) % len(SAMPLES)] for k in range(n)) for i in range(len(SAMPLES))]
    for combo in combos:
        values = iter(combo)
        # a number format gets numbers: "%.0fs" with a name in it would be "Anna's iPhones", which is nothing the app writes
        line = FILL.sub(lambda m: next(values) if m.group(0)[-1] in "srx" or m.group(0).startswith("{") else NUMBERS[len(m.group(0)) % len(NUMBERS)], template)
        out = a.text(line)
        left = a.leaks(out)
        assert left == [], (template, line, out, left)
        # the personal values must not survive
        for secret in ("192.168.1.5", "172.20.4.7", "AA:BB:CC:00:11:22", "93.184.216.34", "Anna's iPhone", "giulia-ipad", "Salotto TV Samsung", "81.174.0.21"):
            assert secret.lower() not in out.lower(), (template, line, out, secret)
        checked += 1
print(f"{len(templates)} messaggi, {checked} combinazioni controllate")
print("TUTTO OK")
