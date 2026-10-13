"""Golden-master test of scan_nmap.tls_ssh_scan with nmap and the XML parser replaced by in-memory fakes that record their calls: 2500 generated port lists (TLS ports, port 22,
services containing https/ssl/ssh, None/empty services, duplicates, more than 12 ports) and parsed hosts (missing, empty, falsy values) must give exactly the same result (or exception)
AND the same nmap arguments as the code before the function was split. tests/golden/tls_ssh_scan.json keeps one sha1 per case plus a readable sample.
Regenerate only on purpose:  TLS_SSH_GOLDEN_UPDATE=1 python tests/check_tls_ssh_scan_golden.py"""
import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_nmap  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "tls_ssh_scan.json"
N = 2500
rng = random.Random(70707)
LOG: list = []
STATE: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


async def fake_run_nmap(args, semaphore=None):
    which = "light" if semaphore is scan_nmap._LIGHT_NMAP_SEMAPHORE else ("heavy" if semaphore is scan_nmap._NMAP_SEMAPHORE else repr(semaphore))
    LOG.append(["run_nmap", args, which])
    return "XML"


def fake_parse_hosts(text):
    LOG.append(["parse_hosts", text])
    return STATE["hosts"]


scan_nmap._run_nmap = fake_run_nmap
scan_nmap._parse_hosts = fake_parse_hosts
PORTS = [22, 80, 443, 8443, 4443, 9443, 5001, 5986, 8006, 8883, 993, 995, 636, 465, 7443, 9090, 21, 23, 53, 8080, 1883, 5000, 6, 0]
SERVICES = [None, "", "http", "https", "ssl/http", "ssh", "openssh", "http-proxy", "ssl", "imaps", "tls", "HTTPS", "microsoft-ds"]


def make_ports():
    ports = []
    for _ in range(rng.randrange(0, 9) if rng.random() < 0.9 else rng.randrange(13, 20)):
        p = {"port": pick(PORTS)}
        if rng.random() < 0.7:
            p["service"] = pick(SERVICES)
        if rng.random() < 0.2:
            p["proto"] = "tcp"
        ports.append(p)
    if rng.random() < 0.01:
        ports.append({"service": "ssh"})        # no "port": KeyError
    return ports


def make_hosts():
    if rng.random() < 0.2:
        return []
    h = {}
    for k in ("tls_subject", "tls_issuer", "ssh_hostkey"):
        if rng.random() < 0.7:
            h[k] = pick(["CN=a", "CN=b", "", None, 0, "ssh-rsa AAA", "x"])
    h["ip"] = "1.2.3.4"
    return [h] + ([{"tls_subject": "second"}] if rng.random() < 0.2 else [])


out = []
for _ in range(N):
    ports = make_ports()
    STATE["hosts"] = make_hosts()
    ip = pick(["192.168.1.5", "10.0.0.9"])
    timeout = pick([20, 5, 33, None])
    kw = {} if timeout is None else {"timeout": timeout}
    LOG.clear()
    try:
        res = asyncio.run(scan_nmap.tls_ssh_scan(ip, ports, **kw))
    except Exception as exc:
        res = ["EXC", type(exc).__name__]
    out.append({"ports": ports, "res": res, "log": list(LOG)})


def digest(x):
    return hashlib.sha1(json.dumps(x).encode()).hexdigest()[:20]


mine = json.loads(json.dumps({"digests": [digest(o) for o in out], "sample": out[:30]}, sort_keys=True))
if os.environ.get("TLS_SSH_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(mine, sort_keys=True, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want["digests"]) == len(mine["digests"]) == N
for i, (x, y) in enumerate(zip(mine["digests"], want["digests"])):
    assert x == y, "case %d differs: %s" % (i, json.dumps(out[i])[:600])
assert mine["sample"] == want["sample"]
assert sum(1 for o in out if not o["log"]) > 100
assert sum(1 for o in out if o["log"] and o["res"] == {}) > 100
assert sum(1 for o in out if isinstance(o["res"], dict) and o["res"]) > 500
assert sum(1 for o in out if isinstance(o["res"], list)) >= 1
assert any(len(o["log"][0][1][2].split(",")) == 12 for o in out if o["log"])
assert any(set(o["res"]) == {"tls_subject", "tls_issuer", "ssh_hostkey"} for o in out if isinstance(o["res"], dict))
print("TUTTO OK")
