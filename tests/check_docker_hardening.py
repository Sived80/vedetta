# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 «Approdo», after an independent security review of Docker mode (27/11). Each check is an attack that worked before the fix:
1) many wrong passwords sent at the same moment were all tried (the wait was checked before the queue of scrypt, the failure counted
   after it): now each attempt is counted before its scrypt, and a second one waiting in the queue is refused at once;
2) a stranger making a wrong attempt now and then kept the owner out from every address (one global wait of 15 minutes): now the
   global count only slows down (at most GLOBAL_MAX_WAIT_S), the long wait is per address, login and setup count apart;
3) a huge body sent to /login was read whole into memory before the size check: now Content-Length is checked first and the body
   is read up to the limit; a form with too many fields is a 400, not a 500;
4) a page of another site (DNS rebinding: a name of the attacker pointing to the LAN address of Vedetta) passed the origin check:
   now the Host must be an address, localhost, a local name (.local, .lan, .home.arpa, .internal) or one of VEDETTA_ALLOWED_HOSTS;
5) a password set from the host while the app was writing the sessions could leave an old session alive: now a session made before
   the last password change is never valid, whatever the sessions file says;
6) the answers of the access check (401, 403, 303) carry the security headers too;
7) a secret file the container cannot read (owned by the host user, mode 600, with every capability dropped) was silently "no Home
   Assistant": now the log says why.
Invented addresses only.
    python tools/run_test.py check_docker_hardening.py"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
os.environ["VEDETTA_MODE"] = "docker"
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import runtime  # noqa: E402
from app.main import app  # noqa: E402
from app.auth import passwords, store, throttle  # noqa: E402
from app.routes import auth_routes  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


GOOD = "correct horse battery staple"
SAME = {"Sec-Fetch-Site": "same-origin"}
store.set_password_hash(passwords.hash_password(GOOD))


def client(address="192.0.2.10", **kw) -> TestClient:
    kw.setdefault("base_url", "http://192.0.2.200:8765")
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False, client=(address, 1), **kw)


def reset() -> None:
    auth_routes.throttle_login.__init__()
    auth_routes.throttle_setup.__init__()


# ---- 1) parallel attempts
async def burst(n: int) -> list[int]:
    transport = httpx.ASGITransport(app=app, client=("192.0.2.7", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://192.0.2.200:8765") as c:
        replies = await asyncio.gather(*[c.post("/login", data={"password": "wrong guess %d" % i}, headers=SAME) for i in range(n)])
    return [r.status_code for r in replies]

reset()
codes = asyncio.run(burst(20))
tried = codes.count(401)
check(tried <= throttle.FREE and codes.count(429) == 20 - tried, "20 wrong passwords at once: only %d tried, the rest refused at once (%s)" % (tried, sorted(set(codes))))

# ---- 2) the owner is not kept out by a stranger
reset()
stranger = client("192.0.2.7")
for i in range(8):
    stranger.post("/login", data={"password": "wrong guess %d" % i}, headers=SAME)
check(stranger.post("/login", data={"password": GOOD}, headers=SAME).status_code == 429, "the stranger's own address waits")
owner = client("192.0.2.10")
check(owner.post("/login", data={"password": GOOD}, headers=SAME).status_code == 303, "the owner, from another address, gets in at once")
now = [0.0]
t = throttle.Throttle(clock=lambda: now[0])
for i in range(200):
    t.failed("192.0.2.%d" % (i % 250 + 1))
check(t.wait("192.0.2.251") <= throttle.GLOBAL_MAX_WAIT_S, "many addresses together: the global wait stays short (%.0f s)" % t.wait("192.0.2.251"))
for _ in range(12):
    t.failed("192.0.2.9")
check(t.wait("192.0.2.9") > throttle.GLOBAL_MAX_WAIT_S, "the address that failed many times waits long (%.0f s)" % t.wait("192.0.2.9"))
check(auth_routes.throttle_login is not auth_routes.throttle_setup, "login and setup count apart")

# ---- 3) bodies
reset()
r = owner.post("/login", content=b"a" * (5 * 1024 * 1024), headers={**SAME, "Content-Type": "application/x-www-form-urlencoded"})
check(r.status_code == 413, "a 5 MB body is refused (%d)" % r.status_code)
r = owner.post("/login", content="&".join("f%d=1" % i for i in range(9)), headers={**SAME, "Content-Type": "application/x-www-form-urlencoded"})
check(r.status_code == 400, "a form with too many fields is a 400, not a 500 (%d)" % r.status_code)


async def endless_body() -> int:
    async def chunks():
        for _ in range(64):
            yield b"a" * 65536
    transport = httpx.ASGITransport(app=app, client=("192.0.2.11", 1))
    async with httpx.AsyncClient(transport=transport, base_url="http://192.0.2.200:8765") as c:
        r = await c.post("/login", content=chunks(), headers={**SAME, "Content-Type": "application/x-www-form-urlencoded"})
    return r.status_code

check(asyncio.run(endless_body()) == 413, "a body without Content-Length is read only up to the limit")

# ---- 4) Host
for host, want in (("192.0.2.200:8765", 303), ("[2001:db8::5]:8765", 303), ("localhost:8765", 303), ("vedetta.local", 303), ("nas.lan:8765", 303),
                   ("vedetta.home.arpa", 303), ("box.internal", 303), ("rebind.attacker.example", 400), ("attacker.example:8765", 400)):
    r = client().get("/ha", headers={"Host": host})
    check(r.status_code == want, "Host %s -> %d (%d)" % (host, want, r.status_code))
os.environ["VEDETTA_ALLOWED_HOSTS"] = "vedetta.example.org, other.example.net"
check(client().get("/ha", headers={"Host": "vedetta.example.org"}).status_code == 303, "a name in VEDETTA_ALLOWED_HOSTS is accepted")
check(client().get("/ha", headers={"Host": "attacker.example"}).status_code == 400, "and the others are still refused")
os.environ.pop("VEDETTA_ALLOWED_HOSTS")

# ---- 5) a password change closes every older session, whatever the sessions file says
reset()
web = client()
web.post("/login", data={"password": GOOD}, headers=SAME)
check(web.get("/api/ha/summary").status_code == 200, "a session is open")
saved = store.SESSIONS_PATH.read_text(encoding="utf-8")
time.sleep(1.1)                                    # the change happens at least one second after the login
store.set_password_hash(passwords.hash_password("another long passphrase here"))
store.SESSIONS_PATH.write_text(saved, encoding="utf-8")      # the app wrote the old sessions back at the same moment
check(web.get("/api/ha/summary").status_code == 401, "a session made before the password change is closed anyway")

# ---- 6) security headers on the answers of the access check
r = client().get("/api/ha/summary")
check(r.status_code == 401 and r.headers.get("x-frame-options") == "SAMEORIGIN" and "frame-ancestors" in r.headers.get("content-security-policy", "")
      and r.headers.get("referrer-policy"), "a 401 carries the security headers")
r = client().get("/ha")
check(r.status_code == 303 and "frame-ancestors" in r.headers.get("content-security-policy", ""), "a 303 to the login too")

# ---- 7) an unreadable secret is told
folder = Path(tempfile.mkdtemp())
runtime.SECRETS_DIR = folder
(folder / "ha_token").write_text("x", encoding="utf-8")
real_read = Path.read_text
Path.read_text = lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, "Permission denied")) if self.name == "ha_token" else real_read(self, *a, **k)
said = []
try:
    value = runtime.secret("ha_token", said.append)
finally:
    Path.read_text = real_read
check(value is None and said and "ha_token" in said[0] and "root" in said[0], "a secret file that cannot be read is told, with the way out: %s" % (said[:1],))

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
