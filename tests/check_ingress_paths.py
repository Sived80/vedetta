"""Base path (HA ingress), data folder and network interface.
 - with an empty prefix the rendered HTML is IDENTICAL to that of the git HEAD templates
   (if git is not available that comparison is skipped);
 - with prefix /api/hassio_ingress/abc every link/asset is prefixed;
 - middleware: X-Ingress-Path, VEDETTA_BASE_PATH, VEDETTA_INGRESS_ONLY (403);
 - VEDETTA_DATA_DIR and VEDETTA_IFACE.
Run from the project root: python tests/check_ingress_paths.py"""
import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from jinja2 import DictLoader, Environment, FileSystemLoader, select_autoescape

from app import i18n
from app.ingress import IngressMiddleware, base_from_headers, template_context
from app.paths import normalize_base

TPL = Path("app/templates")
PREFIX = "/api/hassio_ingress/abc"


def make_env(loader) -> Environment:
    env = Environment(loader=loader, autoescape=select_autoescape(["html"]))
    env.globals.update(t=i18n.t, t_or=i18n.t_or, static_version=lambda p: "1")
    env.filters.update(ago=lambda v: "", uptime=lambda v: "", uptime_short=lambda v: "")
    return env


DEVICE = {
    "id": "d1", "name": "Prova", "is_mobile": False, "ip": "10.0.0.5", "port": 80, "url": "http://10.0.0.5:80",
    "online": True, "uptime": 3600, "mac": "AA:BB:CC:00:00:01", "vendor": None, "signal_kind": None,
    "signal_value": None, "signal_band": None, "signal_label": None, "signal_color": None, "extra": {},
    "scanned_ports": [], "scanned_at": None, "last_seen": None, "title": None, "adapter": None,
}
LANG = "en"
CTX = {
    "ha.html": {"lang": LANG, "lang_auto": True, "languages": i18n.available(), "js_strings": {}, "theme": "auto",
                "transparent": False, "compact": False, "limit": 6},
}


def render(env, name, **extra):
    return env.get_template(name).render(**CTX[name], **extra)


new_env = make_env(FileSystemLoader(str(TPL)))

# 1) empty prefix: identical to the git HEAD templates
try:
    old = {}
    for rel in ("ha.html",):
        old[rel] = subprocess.run(["git", "show", "HEAD:vedetta/app/templates/" + rel], capture_output=True, check=True).stdout.decode("utf-8")
    head_env = make_env(DictLoader(old))
    for name in CTX:
        # the HEAD templates do not use `base`: with base="" the result must match
        before = render(head_env, name)
        after = render(new_env, name, base="")
        assert before == after, "HTML con prefisso vuoto diverso da HEAD: " + name
        # and also when passing a context without `base` (undefined variable = empty string)
        assert render(new_env, name) == before, "base indefinito: " + name
    print("ok: prefisso vuoto identico a HEAD")
except (FileNotFoundError, subprocess.CalledProcessError):
    print("saltato: confronto con git HEAD (git non disponibile)")

# 2) with prefix: every internal URL prefixed
URL_ATTR = re.compile(r'(?<!\(<a )(?:href|src|action)="(/[^"]*)"')  # excludes the example in the JS comment of log.html
for name in CTX:
    html = render(new_env, name, base=PREFIX)
    for url in URL_ATTR.findall(html):
        assert url.startswith(PREFIX + "/"), "URL non prefissato in %s: %s" % (name, url)
    assert 'window.VEDETTA_BASE = "%s"' % PREFIX in html, "VEDETTA_BASE mancante in " + name
    assert PREFIX + "/static/js/base.js" in html
    assert PREFIX + "/static/" in html
assert "VEDETTA_BASE" not in render(new_env, "ha.html", base="")
print("ok: URL dei template prefissati")

# 3) no internal absolute URL in the static sources outside the points covered by the wrapper
for js in list(Path("app/static/js").glob("*.js")) + list(Path("app/frontend/ha/js").glob("*.js")):
    text = js.read_text(encoding="utf-8")
    for m in re.finditer(r"""(?:href|src|action)=\\?["']\s*\+?\s*["']?/""", text):
        raise AssertionError("href/src assoluto in %s: %s" % (js, m.group(0)))
for css in Path("app/frontend/ha/css").glob("*.css"):
    assert "url(/" not in css.read_text(encoding="utf-8").replace("url( /", "url(/"), "url(/...) assoluto in " + str(css)
print("ok: sorgenti statici senza URL assoluti nascosti")

# 4) normalisation and headers
assert normalize_base("/abc/") == "/abc" and normalize_base("") == "" and normalize_base("/") == ""
assert normalize_base("abc") == "" and normalize_base('/a"b') == "" and normalize_base("//evil.com") != "//evil.com/"
assert base_from_headers({b"x-ingress-path": b"/api/hassio_ingress/abc"}) == PREFIX
os.environ.pop("VEDETTA_BASE_PATH", None)
assert base_from_headers({}) == ""
os.environ["VEDETTA_BASE_PATH"] = "/envbase/"
assert base_from_headers({}) == "/envbase"
assert base_from_headers({b"x-ingress-path": b"/hdr"}) == "/hdr"
del os.environ["VEDETTA_BASE_PATH"]

# 5) ASGI middleware
seen = {}


async def inner(scope, receive, send):
    seen["base"] = scope["state"]["base"]
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def call(client_ip, headers=()):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {"type": "http.request"}

    scope = {"type": "http", "client": (client_ip, 1234), "headers": list(headers), "path": "/", "method": "GET"}
    await IngressMiddleware(inner)(scope, receive, send)
    return sent[0]["status"]


seen.clear()
assert asyncio.run(call("192.168.1.9", [(b"x-ingress-path", b"/api/hassio_ingress/abc")])) == 200 and seen["base"] == PREFIX
assert asyncio.run(call("192.168.1.9")) == 200 and seen["base"] == ""
os.environ["VEDETTA_INGRESS_ONLY"] = "1"
assert asyncio.run(call("192.168.1.9")) == 403
assert asyncio.run(call("172.30.32.2")) == 200
assert asyncio.run(call("127.0.0.1")) == 200
del os.environ["VEDETTA_INGRESS_ONLY"]
assert asyncio.run(call("192.168.1.9")) == 200
assert template_context(types.SimpleNamespace(state=types.SimpleNamespace(base="/x"))) == {"base": "/x"}
print("ok: middleware ingress")

# 6) data folder
import app.paths as paths
default = Path("config").resolve()
assert paths.DATA_DIR.resolve() == default or "VEDETTA_DATA_DIR" in os.environ
with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:  # Windows: the .db stays open
    target = Path(tmp) / "nuova" / "dati"
    os.environ["VEDETTA_DATA_DIR"] = str(target)
    for mod in ("app.paths", "app.storage.devices_config", "app.storage.settings", "app.storage.history", "app.scan.dhcp", "app.storage.blocklist",
                "app.recognition.brands", "app.recognition.vendor_lookup"):
        sys.modules.pop(mod, None)
    paths = importlib.import_module("app.paths")
    assert target.is_dir(), "DATA_DIR non creata"
    for mod, attr, name in (("app.storage.devices_config", "DEVICES_PATH", "devices.yaml"), ("app.storage.settings", "SETTINGS_PATH", "settings.json"),
                            ("app.storage.history", "DB_PATH", "vedetta.db"), ("app.scan.dhcp", "STORE_PATH", "dhcp_seen.json"),
                            ("app.storage.blocklist", "PATH", "ignored.json"), ("app.recognition.brands", "_USER_PATH", "brands.json"),
                            ("app.recognition.vendor_lookup", "USER_OUI_PATH", "oui-ieee.txt")):
        got = getattr(importlib.import_module(mod), attr)
        assert got == target / name, "%s.%s = %s" % (mod, attr, got)
    del os.environ["VEDETTA_DATA_DIR"]
print("ok: VEDETTA_DATA_DIR")

# 7) network interface
from app import iface
ROUTES = ("Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n"
          "wlan0\t00000000\t0100A8C0\t0003\t0\t0\t600\t00000000\n"
          "eth1\t00000000\t0100A8C0\t0003\t0\t0\t100\t00000000\n"
          "eth1\t0000A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\n")
assert iface.parse_default_route(ROUTES) == "eth1"
assert iface.parse_default_route("Iface\tDestination\n") is None
iface.lan_iface.cache_clear()
os.environ["VEDETTA_IFACE"] = "end0"
assert iface.lan_iface() == "end0"
del os.environ["VEDETTA_IFACE"]
iface.lan_iface.cache_clear()
assert iface.lan_iface()  # detected or eth0 fallback
print("ok: interfaccia di rete")

# 8) DNS packages of the reverse resolution
from app.scan import scanner
q = scanner._build_ptr_query("192.168.50.44")
assert q[12:].startswith(b"\x0244\x0250\x03168\x03192\x07in-addr\x04arpa\x00")
answer = (b"\x00\x00\x84\x00\x00\x00\x00\x01\x00\x00\x00\x00" + q[12:-4] + b"\x00\x0c\x00\x01\x00\x00\x00x\x00\x0f"
          + b"\x05led-a\x05local\x00")
assert scanner._parse_ptr_answer(answer) == "led-a.local"
assert scanner._parse_ptr_answer(b"\x00") is None
print("ok: pacchetti PTR")
print("TUTTO OK")
