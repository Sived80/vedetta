"""Golden-master test of scan_nmap._parse_hosts: 400 generated nmap XML documents (hosts up/down, with and without MAC, vendor, host name, open/closed ports,
services probed or guessed, http-title, ssl-cert, ssh-hostkey, broken documents) must give exactly the output stored in tests/golden/nmap_parse.json,
written from the code as it was before the function was split.   Regenerate only on purpose:  NMAP_GOLDEN_UPDATE=1 python tests/check_nmap_parse_golden.py"""
import json
import os
import random
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_nmap  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "nmap_parse.json"
N = 400
rng = random.Random(777)


def pick(seq):
    return seq[rng.randrange(len(seq))]


def q(s):
    return quoteattr(s)


def port():
    st = pick(["open", "open", "closed", "filtered"])
    svc = pick([None, '<service name="http" product="nginx" version="1.2" method="probed"/>', '<service name="ssh" method="table"/>', '<service name="https"/>'])
    scripts = ""
    if rng.random() < 0.5:
        scripts += f'<script id="http-title" output={q(pick(["Login", "", "Router <b>", "Home"]))}/>'
    if rng.random() < 0.3:
        scripts += f'<script id="ssl-cert" output={q(pick(["Subject: commonName=nas.local/organizationName=Acme\nIssuer: commonName=CA", "", "garbage"]))}/>'
    if rng.random() < 0.3:
        scripts += f'<script id="ssh-hostkey" output={q(pick(["256 aa:bb:cc (ED25519)\n2048 dd:ee (RSA)", "", "x"]))}/>'
    state = "" if rng.random() < 0.05 else f'<state state="{st}"/>'
    return f'<port protocol="tcp" portid="{pick([22, 80, 443, 8006, 5001, 53])}">{state}{svc or ""}{scripts}</port>'


def host():
    addrs = ""
    if rng.random() < 0.9:
        addrs += f'<address addr="10.0.{rng.randrange(3)}.{rng.randrange(1, 250)}" addrtype="ipv4"/>'
    if rng.random() < 0.6:
        addrs += f'<address addr="{pick(["AC:84:C6:11:22:33", "00:11:22:33:44:55", "AA:BB:CC:DD:EE:FF"])}" addrtype="mac"' + pick(["", ' vendor="TP-Link"', ' vendor=""']) + "/>"
    if rng.random() < 0.1:
        addrs += '<address addr="fe80::1" addrtype="ipv6"/>'
    hn = f'<hostnames><hostname name="{pick(["nas", "cam1", "x.local"])}"/></hostnames>' if rng.random() < 0.5 else ""
    ports = "<ports>" + "".join(port() for _ in range(rng.randrange(0, 6))) + "</ports>" if rng.random() < 0.85 else ""
    status = pick(['<status state="up"/>'] * 5 + ['<status state="down"/>', ""])
    return f"<host>{status}{addrs}{hn}{ports}</host>"


out = []
for _ in range(N):
    xml = "<nmaprun>" + "".join(host() for _ in range(rng.randrange(0, 6))) + "</nmaprun>"
    if rng.random() < 0.05:
        xml = xml[: rng.randrange(1, len(xml))]            # broken document
    try:
        out.append(scan_nmap._parse_hosts(xml))
    except Exception as exc:
        out.append({"exception": type(exc).__name__})
out = json.loads(json.dumps(out, sort_keys=True, default=str))
if os.environ.get("NMAP_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:500])
hosts = [h for o in out if isinstance(o, list) for h in o]
assert len(hosts) > 300 and any(h["mac"] for h in hosts) and any(h.get("tls_subject") for h in hosts) and any(h.get("ssh_hostkey") for h in hosts) and any(h["http_title"] for h in hosts), "scenarios too uniform"
assert not any(isinstance(o, dict) for o in out)
print("TUTTO OK")
