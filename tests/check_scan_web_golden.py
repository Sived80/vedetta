"""Golden-master test of scan_web._confirm_http_port (a direct GET that proves a port speaks HTTP: plain, then TLS if the plain answer is not good enough) and scan_web._confirm_http_ports
(marks a host's stable ports in place): 4000 generated connections and 2000 generated port lists. The network is replaced by in-memory fakes driven by a random script: `asyncio.open_connection`
(refusals, timeouts), the reader and the writer (first answer, extra chunks, timeouts and resets in the middle of the reading, a failing `wait_closed`), `asyncio.wait_for` (which only records the
timeout) and `_https_get` (no answer, error, a TLS page with or without certificate subject); `_confirm_http_ports` runs on a fake `_confirm_http_port`. Every call that reaches a fake is recorded
with its arguments (the order, the sizes asked for and the timeouts count), and the returned dictionaries / the marked ports (key order included) must match tests/golden/scan_web.json,
written from the code as it was before the two functions were split.
Regenerate only on purpose:  SCANWEB_GOLDEN_UPDATE=1 python tests/check_scan_web_golden.py"""
import asyncio
import copy
import json
import os
import random
import sys
import types
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_web  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "scan_web.json"
N = 4000
N_PORTS = 2000
rng = random.Random(31415926)
REAL_ASYNCIO = asyncio


def pick(seq):
    return seq[rng.randrange(len(seq))]


STATUS = ["HTTP/1.1 200 OK", "HTTP/1.0 200 OK", "HTTP/1.1 301 Moved", "HTTP/1.1 302 Found", "HTTP/1.1 404 Not Found", "HTTP/1.1 401 Unauthorized", "HTTP/1.1 500 Err", "HTTP/2 200",
          "HTTP/1.1 abc", "HTTP/1.1 403 Forbidden", "HTTP/1.1 204 No", "HTTP/1.1 400 Bad"]
HEADERS = ["", "Server: nginx", "server:  Apache/2.4  ", "Location: https://x/", "Location: http://x/", "LOCATION: HTTPS://x/", "Server: " + "s" * 150, "Content-Type: text/html",
           "Server:", "X-Other: 1"]
BODIES = ["", "<html><title>Home</title></html>", "<title>  Spaced\n  Title </title>", "<TITLE lang=x>Upper</TITLE>", "<title></title>", "<title>" + "T" * 200 + "</title>", "x" * 70,
          "x" * 59, "x" * 60, "<title>Login</title>", "<title>Ünï</title>", "no title here", "<html><body>" + "y" * 100 + "</body></html>", "<title>unterminated"]
NON_HTTP = [b"", b"SSH-2.0-OpenSSH_9", b"\x15\x03\x01\x00\x02\x02\x0a", b"HTTP", b"http/1.1 200 OK\r\n\r\nx", b"220 smtp ready\r\n"]
SUBJECTS = [None, "CN=device", "", "O=Acme, CN=x"]


def http_response():
    status = pick(STATUS)
    headers = [h for h in (pick(HEADERS), pick(HEADERS)) if h]
    sep = pick(["\r\n"] * 8 + ["\n"])
    head = status + sep + sep.join(headers)
    gap = pick(["\r\n\r\n"] * 9 + ["\r\n", ""])
    body = pick(BODIES)
    data = (head + gap + body).encode("utf-8")
    r = rng.random()
    if r < 0.04:  # a page that fills the read buffer, around the limit of the loop
        pad = pick([65536, 65535, 65534, 65000])
        data = data + b"z" * max(0, pad - len(data))
    return data


def first_answer():
    r = rng.random()
    if r < 0.7:
        return http_response()
    if r < 0.9:
        return pick(NON_HTTP)
    return pick([asyncio.TimeoutError(), ConnectionResetError(), OSError("boom")])


def chunk_script():
    n = pick([0, 0, 1, 1, 2, 3])
    out = []
    for _ in range(n):
        r = rng.random()
        if r < 0.6:
            out.append(pick([b"more body", b"x" * 30, b"</html>", b"q" * 20000, b"\r\n"]))
        elif r < 0.75:
            out.append(b"")
        elif r < 0.9:
            out.append(asyncio.TimeoutError())
        else:
            out.append(pick([ConnectionResetError(), OSError("reset")]))
    return out


def tls_result():
    r = rng.random()
    if r < 0.3:
        return None
    if r < 0.4:
        return "raise"
    if r < 0.45:
        return (b"", pick(SUBJECTS))
    return (http_response() if rng.random() < 0.7 else pick(NON_HTTP), pick(SUBJECTS))


calls = []


def install(script):
    class Reader:
        async def read(self, n):
            calls.append(["read", n])
            item = script["reads"].pop(0) if script["reads"] else b""
            if isinstance(item, BaseException):
                raise item
            return item

    class Writer:
        def write(self, data):
            calls.append(["write", data.decode()])

        async def drain(self):
            calls.append(["drain"])

        def close(self):
            calls.append(["close"])

        async def wait_closed(self):
            calls.append(["wait_closed"])
            if script["wait_closed_fails"]:
                raise OSError("closed badly")

    async def open_connection(ip, port):
        calls.append(["open", ip, port])
        if script["open_error"] is not None:
            raise script["open_error"]
        return Reader(), Writer()

    async def wait_for(aw, timeout=None):
        calls.append(["wait_for", timeout])
        return await REAL_ASYNCIO.wait_for(aw, timeout)

    async def https_get(ip, port, timeout):
        calls.append(["https_get", ip, port, timeout])
        if script["tls"] == "raise":
            raise ValueError("tls broke")
        return script["tls"]

    scan_web.asyncio = types.SimpleNamespace(open_connection=open_connection, wait_for=wait_for, TimeoutError=REAL_ASYNCIO.TimeoutError, gather=REAL_ASYNCIO.gather)
    scan_web._https_get = https_get


# ---------------------------------------------------------------- _confirm_http_port
one_out = []
stats = {"none": 0, "http": 0, "https": 0, "plain_kept_after_tls_fail": 0, "extra_chunks": 0, "usable": 0, "unusable": 0, "server": 0, "title": 0, "status_none": 0, "open_error": 0, "full": 0,
         "subject": 0, "wait_closed_fails": 0, "redirect_https": 0}
for _ in range(N):
    script = {"open_error": pick([None] * 12 + [OSError("refused"), asyncio.TimeoutError()]), "reads": [first_answer()] + chunk_script(), "wait_closed_fails": rng.random() < 0.1, "tls": tls_result()}
    del calls[:]
    install(script)
    ip, port = pick(["192.168.1.7", "10.0.0.2"]), pick([80, 443, 8123, 1884])
    timeout = pick([None, None, 0.5, 1.5, 3.0, 5.0])
    try:
        r = asyncio.run(scan_web._confirm_http_port(ip, port) if timeout is None else scan_web._confirm_http_port(ip, port, timeout))
        res = {"ret": r, "calls": copy.deepcopy(calls)}
    except Exception as exc:
        res = {"exception": type(exc).__name__, "calls": copy.deepcopy(calls)}
    one_out.append(res)
    r = res.get("ret")
    stats["none"] += res.get("ret") is None
    stats["open_error"] += script["open_error"] is not None
    stats["wait_closed_fails"] += script["wait_closed_fails"] and any(c[0] == "wait_closed" for c in calls)
    stats["extra_chunks"] += sum(1 for c in calls if c[0] == "read") > 1
    stats["full"] += any(c == ["read", 1] or (c[0] == "read" and c[1] < 65536 and c[1] > 0 and c[1] < 100) for c in calls)
    if r:
        stats["http" if r["scheme"] == "http" else "https"] += 1
        stats["usable"] += r["usable"]
        stats["unusable"] += not r["usable"]
        stats["server"] += r["server"] is not None
        stats["title"] += r["title"] is not None
        stats["status_none"] += r["status"] is None
        stats["subject"] += bool(r["tls_subject"])
        stats["plain_kept_after_tls_fail"] += r["scheme"] == "http" and any(c[0] == "https_get" for c in calls)

# ---------------------------------------------------------------- _confirm_http_ports
two_out = []
pstats = {"empty": 0, "found": 0, "missing": 0, "subject": 0, "ephemeral": 0, "kept_keys": 0}
PORT_NUMS = [22, 80, 443, 8123, 1884, 49151, 49152, 49153, 60000, 0, 1]
for _ in range(N_PORTS):
    ports = []
    for _ in range(pick([0, 1, 2, 3, 5, 8])):
        p = {"port": pick(PORT_NUMS)}
        if rng.random() < 0.5:
            p["service"] = pick(["http", "ssh", "mqtt"])
        if rng.random() < 0.3:
            p["web_ui"] = pick([True, False])
        if rng.random() < 0.3:
            p["tls_subject"] = "CN=old"
        if rng.random() < 0.2:
            p["http_server"] = "old"
        ports.append(p)
    answers = {}
    for p in ports:
        r = rng.random()
        if r < 0.3:
            answers[p["port"]] = None
        elif r < 0.35:
            answers[p["port"]] = {}
        else:
            d = {"tls_subject": pick(SUBJECTS), "size": pick([0, 5, 70, 4000]), "server": pick([None, "nginx", ""]), "title": pick([None, "Home", ""]), "status": 200,
                 "scheme": pick(["http", "https"]), "usable": pick([True, False])}
            if rng.random() < 0.15:
                del d["tls_subject"]
            answers[p["port"]] = d
    del calls[:]

    async def fake_confirm(ip, port, answers=answers):
        calls.append(["confirm", ip, port])
        await REAL_ASYNCIO.sleep(0)
        return copy.deepcopy(answers.get(port))

    scan_web._confirm_http_port = fake_confirm
    scan_web.asyncio = REAL_ASYNCIO
    try:
        asyncio.run(scan_web._confirm_http_ports("192.168.1.7", ports))
        res = {"ports": ports, "calls": copy.deepcopy(calls)}
    except Exception as exc:
        res = {"exception": type(exc).__name__, "ports": ports, "calls": copy.deepcopy(calls)}
    two_out.append(res)
    pstats["empty"] += not calls
    pstats["found"] += any(p.get("http_page_title") is not None for p in ports)
    pstats["missing"] += any(p.get("http_body_size", 0) is None for p in ports)
    pstats["subject"] += any(p.get("tls_subject") == "CN=device" for p in ports)
    pstats["ephemeral"] += any(p["port"] >= 49152 for p in ports)
    pstats["kept_keys"] += any("service" in p and "web_ui" in p for p in ports)

out = {"one": one_out, "many": two_out}
text_out = json.dumps(out)  # no sort_keys: the key order counts
if os.environ.get("SCANWEB_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(text_out, encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
for part, n in (("one", N), ("many", N_PORTS)):
    assert len(want[part]) == len(out[part]) == n
    for i, (x, y) in enumerate(zip(out[part], want[part])):
        assert json.dumps(x) == json.dumps(y), "%s case %d differs: %s" % (part, i, json.dumps([x, y])[:900])
assert text_out == GOLDEN.read_text(encoding="utf-8"), "key order or formatting differs"
assert all(stats[k] > 100 for k in ("none", "http", "https", "plain_kept_after_tls_fail", "extra_chunks", "usable", "unusable", "server", "title", "open_error", "subject", "wait_closed_fails")), \
    "too uniform: %s" % stats
assert stats["status_none"] > 10, stats
assert all(pstats[k] > 100 for k in pstats), "too uniform: %s" % pstats
print("TUTTO OK")
