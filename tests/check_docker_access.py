# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 «Approdo»: Vedetta as a container of its own (Docker, for Home Assistant Container). The page is on a port of the network, so:
- before a password exists every page leads to /setup, which asks the one-time code of the log; the API answers 401;
- after it, every page leads to /login and the API answers 401 without the session; /setup is gone (404);
- a request that changes something must come from the page itself (Sec-Fetch-Site or Origin) and, for the API, carry X-Vedetta-Request;
- wrong attempts wait (429), the cookie is HttpOnly and SameSite=Lax (Secure only on HTTPS), a new id at each login, logout ends it on the
  server, a password set from the host (vedetta-passwd) closes every session at once;
- the headers only the Supervisor may send (X-Ingress-Path, X-Remote-User-ID) are ignored; /healthz answers only inside the container;
- the security headers: frame-ancestors only for valid origins, no X-Frame-Options then, Permissions-Policy, no-store on the API;
- under the Supervisor none of this exists (/login is 404, the page needs no session).
Invented addresses only (192.0.2.x, documentation range).
    python tools/run_test.py check_docker_access.py"""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
os.environ["VEDETTA_MODE"] = "docker"
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.auth import passwords, store  # noqa: E402
from app.routes import auth_routes  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


ORIGIN = {"Origin": "http://testserver"}
SAME = {"Sec-Fetch-Site": "same-origin"}
API = {**SAME, "X-Vedetta-Request": "1"}
GOOD = "correct horse battery staple"


def client(**kw) -> TestClient:
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False, **kw)


web = client()

# ---- 1) no password yet: everything leads to the setup
r = web.get("/ha")
check(r.status_code == 303 and r.headers["location"] == "/setup", "no password: the page leads to /setup (%s %s)" % (r.status_code, r.headers.get("location")))
check(web.get("/").headers.get("location") == "/setup", "the root too")
check(web.get("/api/ha/devices").status_code == 401, "the API answers 401")
check(web.get("/static/ha/boot.js").status_code == 401, "the files of the page too")
check(web.get("/login").headers.get("location") == "/setup", "the login page sends to the setup while there is no password")
code = auth_routes.setup_code.make().replace("-", "")
page = web.get("/setup")
check(page.status_code == 200 and 'name="code"' in page.text and "<script" not in page.text, "the setup page asks the code and has no script")
check("no-store" in page.headers.get("cache-control", ""), "the setup page is not cached")
r = web.post("/setup", data={"code": code, "password": GOOD, "confirm": GOOD})
check(r.status_code == 403, "a setup form without origin is refused (CSRF)")
r = web.post("/setup", data={"code": code, "password": GOOD, "confirm": GOOD}, headers={"Origin": "http://192.0.2.66"})
check(r.status_code == 403, "a setup form from another site is refused")
r = web.post("/setup", data={"code": "WRONGCODE234", "password": GOOD, "confirm": GOOD}, headers=ORIGIN)
check(r.status_code == 401 and not store.has_password(), "a wrong code sets nothing")
r = web.post("/setup", data={"code": code, "password": "short", "confirm": "short"}, headers=ORIGIN)
check(r.status_code == 400 and not store.has_password(), "a short password is refused")
r = web.post("/setup", data={"code": code, "password": GOOD, "confirm": GOOD + "x"}, headers=ORIGIN)
check(r.status_code == 400 and not store.has_password(), "two different passwords are refused")
r = web.post("/setup", data={"code": code.lower(), "password": GOOD, "confirm": GOOD}, headers=ORIGIN)
cookie = r.headers.get("set-cookie", "")
check(r.status_code == 303 and r.headers["location"] == "/ha" and store.has_password(), "the right code and a good password: set, then the page")
check("vedetta_session=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie.replace("Lax", "lax") and "Secure" not in cookie and "Path=/" in cookie,
      "the cookie is HttpOnly, SameSite=Lax, no Secure on HTTP: %s" % cookie.split(";", 1)[1:])
check(store.password_hash().startswith("scrypt$17$8$1$") and GOOD not in open(store.AUTH_PATH, encoding="utf-8").read(), "only the scrypt hash is on disk")
check(web.get("/setup").status_code == 404 and web.post("/setup", data={}, headers=ORIGIN).status_code == 404, "after it the setup page is gone")
check(not auth_routes.setup_code.active(), "the code cannot be used again")

# ---- 2) the session
check(web.get("/ha").status_code == 200, "with the session the page opens")
check(web.get("/api/ha/summary").status_code == 200, "and the API answers")
check(web.post("/api/refresh", headers=SAME).status_code == 403, "a change without X-Vedetta-Request is refused")
check(web.post("/api/refresh", headers={"X-Vedetta-Request": "1"}).status_code == 403, "a change without origin is refused")
check(web.post("/api/refresh", headers={"X-Vedetta-Request": "1", "Sec-Fetch-Site": "cross-site"}).status_code == 403, "a change from another site is refused")
check(web.post("/api/refresh", headers=API).status_code == 200, "a change from the page goes through")
check(web.post("/api/refresh", headers={"X-Vedetta-Request": "1", "Origin": "http://testserver"}).status_code == 200, "Origin equal to the address is enough without fetch metadata")
page = web.get("/ha", headers={"X-Ingress-Path": "/api/hassio_ingress/evil"})
check("hassio_ingress" not in page.text, "X-Ingress-Path is ignored in Docker")
check('"docker": true' in page.text, "the page knows it runs in Docker (logout, updates)")
check(web.get("/healthz").status_code == 404, "/healthz is 404 from the network")
check(client(client=("127.0.0.1", 50000)).get("/healthz").status_code in (200, 503), "and answers inside the container")

# ---- 3) headers
api = web.get("/api/ha/summary")
check(api.headers.get("cache-control") == "no-store", "the API is not cached")
check("camera=()" in api.headers.get("permissions-policy", "") and api.headers.get("cross-origin-opener-policy") == "same-origin", "Permissions-Policy and COOP")
check(api.headers.get("x-frame-options") == "SAMEORIGIN" and "frame-ancestors 'self';" in api.headers.get("content-security-policy", ""), "no frame ancestor: only this origin")
os.environ["VEDETTA_FRAME_ANCESTORS"] = "http://192.0.2.10:8123, *, https://*.example.com, javascript:alert(1), http://192.0.2.11/path https://192.0.2.12"
h = web.get("/api/ha/summary").headers
check("frame-ancestors 'self' http://192.0.2.10:8123 https://192.0.2.12;" in h.get("content-security-policy", ""), "only valid origins are frame ancestors: %s" % h.get("content-security-policy", "").split("frame-ancestors")[1][:80])
check("x-frame-options" not in h, "with frame ancestors there is no X-Frame-Options")
os.environ.pop("VEDETTA_FRAME_ANCESTORS")

# ---- 4) logout, login, wrong attempts
r = web.post("/logout", headers=SAME)
check(r.status_code == 303 and r.headers["location"] == "/login", "logout leads to the login")
check(web.get("/api/ha/summary").status_code == 401, "after the logout the session is closed")
old = client()
r = old.post("/login", data={"password": GOOD, "next": "//192.0.2.66/x"}, headers=ORIGIN)
check(r.status_code == 303 and r.headers["location"] == "/ha", "after the login the page; a next to another host is ignored (%s)" % r.headers.get("location"))
r = client().post("/login", data={"password": GOOD, "next": "/ha?theme=dark"}, headers=ORIGIN)
check(r.headers.get("location") == "/ha?theme=dark", "a next inside the app is kept")
check(old.get("/api/ha/summary").status_code == 200, "the session works")
first = old.cookies.get("vedetta_session")
old.post("/login", data={"password": GOOD}, headers=ORIGIN)
check(old.cookies.get("vedetta_session") != first, "a new session id at each login")
https = client(base_url="https://testserver")
r = https.post("/login", data={"password": GOOD}, headers={"Origin": "https://testserver"})
check("__Host-vedetta_session=" in r.headers.get("set-cookie", "") and "Secure" in r.headers.get("set-cookie", ""), "on HTTPS the cookie is __Host- and Secure")
bad = client(client=("192.0.2.77", 1))
codes = [bad.post("/login", data={"password": "wrong password number %d" % i}, headers=ORIGIN).status_code for i in range(7)]
check(codes[:5] == [401] * 5 and codes[5] == 429, "five wrong attempts, then a wait: %s" % codes)
page = bad.post("/login", data={"password": GOOD}, headers=ORIGIN)
check(page.status_code == 429, "during the wait even the right password waits")
auth_routes.throttle.succeeded("192.0.2.77")
check(web.post("/login", data={"password": GOOD}, headers={"Origin": "http://192.0.2.66"}).status_code == 403, "a login form from another site is refused")

# ---- 5) a password set from the host closes every session at once (another process: only the files change)
check(old.get("/api/ha/summary").status_code == 200, "before: the session is open")
from app.auth import cli  # noqa: E402
import io  # noqa: E402
sys.stdin = io.StringIO("another long passphrase for vedetta\n")
check(cli.main(["--stdin"]) == 0, "vedetta-passwd --stdin sets a new password")
check(old.get("/api/ha/summary").status_code == 401, "after: the old session is closed")
sys.stdin = io.StringIO("short\n")
check(cli.main(["--stdin"]) == 1, "vedetta-passwd refuses a short password")
check(passwords.verify("another long passphrase for vedetta", store.password_hash()), "the new password is the one stored")

# ---- 6) under the Supervisor none of this exists
os.environ["VEDETTA_MODE"] = "addon"
addon = client()
check(addon.get("/login").status_code == 404 and addon.get("/setup").status_code == 404, "under the Supervisor /login and /setup are 404")
check(addon.get("/api/ha/summary").status_code == 200, "and the API needs no session (Home Assistant logs the person in)")
check('"docker": false' in addon.get("/ha").text, "the page knows it is not in Docker")
os.environ["VEDETTA_MODE"] = "docker"

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
