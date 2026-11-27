# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 «Approdo»: the pieces of Docker mode on their own.
- runtime: the mode (Supervisor token = app of Home Assistant), secrets from a file first, the websocket of Home Assistant from its
  address (no user or password in the URL), the token of Docker only with an address;
- passwords: scrypt with the OWASP minimum, the NIST rules (15 to 128, no composition, common ones refused), a stored text that is not ours;
- throttle: five free attempts per address, then 1 s doubling up to 15 minutes; the whole app only slowed (at most 30 s); never a permanent lock;
- setup code: one hour, once, spaces/dashes/case do not matter;
- update check of Docker: only a newer plain version is "available", drafts and test tags are not.
Invented values only.
    python tools/run_test.py check_docker_runtime.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import runtime  # noqa: E402
from app.auth import passwords, setup, throttle  # noqa: E402
from app.ha import ha_registry, ha_update  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


for k in ("VEDETTA_MODE", "SUPERVISOR_TOKEN", "VEDETTA_HA_URL", "VEDETTA_HA_TOKEN", "VEDETTA_HA_TOKEN_FILE", "VEDETTA_HA_WS"):
    os.environ.pop(k, None)
runtime.SECRETS_DIR = Path(tempfile.mkdtemp())

# ---- mode
check(runtime.mode() == "docker", "no Supervisor token: Docker")
os.environ["SUPERVISOR_TOKEN"] = "x"
check(runtime.mode() == "addon" and runtime.ha_ws_url() == "ws://supervisor/core/websocket", "with it: the app of Home Assistant, through the Supervisor")
os.environ["VEDETTA_MODE"] = "docker"
check(runtime.mode() == "docker", "VEDETTA_MODE wins")
os.environ.pop("SUPERVISOR_TOKEN")
os.environ.pop("VEDETTA_MODE")

# ---- the address of Home Assistant
for url, ws in (("http://192.0.2.10:8123", "ws://192.0.2.10:8123/api/websocket"), ("https://ha.example.org/", "wss://ha.example.org/api/websocket"),
                ("http://192.0.2.10:8123/api/websocket", "ws://192.0.2.10:8123/api/websocket"), ("https://example.org/ha/", "wss://example.org/ha/api/websocket"),
                ("192.0.2.10:8123", None), ("ftp://192.0.2.10", None), ("http://user:pw@192.0.2.10:8123", None), ("http://192.0.2.10:8123/?x=1", None), ("", None)):
    check(runtime.websocket_of(url) == ws, "%r -> %r" % (url, runtime.websocket_of(url)))
check(ha_registry.token() is None and ha_registry.ws_url() is None, "Docker without an address: no Home Assistant")
check("VEDETTA_HA_URL" in ha_registry.missing_token(), "and the status says what is missing")
os.environ["VEDETTA_HA_URL"] = "http://192.0.2.10:8123"
check(ha_registry.token() is None, "an address without a token: still none")
warned = []
os.environ["VEDETTA_HA_TOKEN"] = "env-token-value"
check(runtime.ha_token(warned.append) == "env-token-value" and len(warned) == 1 and "env-token-value" not in warned[0], "a token from the variable works, with one warning that never shows it")
runtime.ha_token(warned.append)
check(len(warned) == 1, "the warning is said once")
(runtime.SECRETS_DIR / "ha_token").write_text("  secret-file-token\n", encoding="utf-8")
check(ha_registry.token() == "secret-file-token", "/run/secrets/ha_token wins over the variable, trimmed")
own = Path(tempfile.mkdtemp()) / "t"
own.write_text("named-file-token", encoding="utf-8")
os.environ["VEDETTA_HA_TOKEN_FILE"] = str(own)
check(ha_registry.token() == "named-file-token" and ha_registry.ws_url() == "ws://192.0.2.10:8123/api/websocket", "VEDETTA_HA_TOKEN_FILE wins over all")
os.environ["VEDETTA_HA_TOKEN_FILE"] = str(own) + ".missing"
check(ha_registry.token() == "secret-file-token", "a missing file falls back to the next source")
for k in ("VEDETTA_HA_URL", "VEDETTA_HA_TOKEN", "VEDETTA_HA_TOKEN_FILE"):
    os.environ.pop(k)

# ---- port
for value, want in (("", 8765), ("9000", 9000), ("0", 8765), ("70000", 8765), ("abc", 8765)):
    os.environ["VEDETTA_PORT"] = value
    check(runtime.port() == want, "port %r -> %d" % (value, runtime.port()))
os.environ.pop("VEDETTA_PORT")

# ---- passwords
stored = passwords.hash_password("correct horse battery staple")
check(stored.startswith("scrypt$17$8$1$") and len(stored.split("$")) == 6, "scrypt N=2^17 r=8 p=1, salt and hash stored with the parameters")
check(passwords.verify("correct horse battery staple", stored) and not passwords.verify("correct horse battery stapl", stored), "the right password matches, a near one does not")
check(passwords.hash_password("correct horse battery staple") != stored, "a new salt each time")
check(not passwords.verify("x", "plain-text") and not passwords.verify("x", "scrypt$30$8$1$AA$AA") and not passwords.verify("x" * 129, stored),
      "a stored text that is not ours, absurd parameters, a too long password: just False")
check(not passwords.needs_rehash(stored) and passwords.needs_rehash("scrypt$14$8$1$AA$AA"), "weaker parameters are re-hashed")
for pw, want in (("a" * 14, "too_short"), ("x" * 129, "too_long"), ("aaaaaaaaaaaaaaaaaa", "too_common"), ("passwordpassword", "too_common"),
                 ("vedettavedetta12", "too_common"), ("Correct horse battery staple", None), ("ÄÖÜ ünïcödé pässwörd ✓", None), ("123456789012345", "too_common")):
    check(passwords.problem(pw) == want, "%r -> %s" % (pw[:20], passwords.problem(pw)))

# ---- throttle
now = [1000.0]
t = throttle.Throttle(clock=lambda: now[0])
for _ in range(5):
    check(t.wait("192.0.2.1") == 0, "free attempt") if _ == 4 else t.wait("192.0.2.1")
    t.failed("192.0.2.1")
check(abs(t.wait("192.0.2.1") - 1.0) < 1e-6, "after five wrong attempts: 1 s")
t.failed("192.0.2.1")
check(abs(t.wait("192.0.2.1") - 2.0) < 1e-6, "then 2 s")
check(t.wait("192.0.2.2") == 0, "another address does not wait for the mistakes of one (the global count only slows many addresses together)")
for _ in range(30):
    t.failed("192.0.2.1")
check(abs(t.wait("192.0.2.1") - throttle.MAX_WAIT_S) < 1e-6, "never more than 15 minutes")
now[0] += throttle.MAX_WAIT_S + 1
check(t.wait("192.0.2.1") == 0, "after the wait it may try again (no permanent lock)")
t.succeeded("192.0.2.1")
t.failed("192.0.2.1")
check(t.wait("192.0.2.1") == 0, "a right password clears the count")

# ---- setup code
now[0] = 0.0
code = setup.SetupCode(clock=lambda: now[0])
shown = code.make()
check(len(shown) == 14 and shown.count("-") == 2 and all(c in setup.ALPHABET + "-" for c in shown), "12 characters in groups of four: %s" % ("x" * len(shown)))
check(code.matches(shown.lower().replace("-", " ")) and not code.matches("AAAA-AAAA-AAAA"), "case, spaces and dashes do not matter; another code does not match")
now[0] = setup.VALID_S + 1
check(not code.active() and not code.matches(shown), "after an hour it no longer works")
now[0] = 0.0
code.make()
code.used()
check(not code.active(), "used once, gone")

# ---- update check of Docker
p = ha_update.parse_release
check(p({"tag_name": "v1.2.0"}, "1.1.0") == {"available": True, "installed": "1.1.0", "latest": "1.2.0"}, "a newer release is available")
check(p({"tag_name": "v1.1.0"}, "1.1.0")["available"] is False and p({"tag_name": "v1.0.9"}, "1.1.0")["available"] is False, "the same or an older one is not")
check(p({"tag_name": "v1.2.0", "prerelease": True}, "1.1.0") is None and p({"tag_name": "v1.2.0", "draft": True}, "1.1.0") is None, "drafts and pre-releases are ignored")
check(p({"tag_name": "1.2.0-test"}, "1.1.0") is None and p([], "1.1.0") is None, "a test tag or a strange answer: nothing")
check(p({"tag_name": "v1.2.0"}, "1.1.0.7")["available"] is False, "a debug build never sees an update")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
