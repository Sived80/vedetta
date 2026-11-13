"""Issue #48: the /ha page must not need an inline script to start. Behind a reverse proxy that adds its own Content-Security-Policy (or rewrites
the scripts of a page), the inline scripts with the nonce of Vedetta's policy do not run: the texts (VEDETTA_I18N) and the ingress prefix
(VEDETTA_BASE) were missing, every request went to the wrong address and the page showed js.ha.error.title. Now:
  - every <script> of the page is either a file of the app (src) or a block of data (type="application/json") that no browser runs;
  - the data of the start (prefix, language, texts, languages) is that one block, valid JSON, safe inside the page (no "</script>" can end it);
  - static/ha/boot.js (a file of the app, allowed by any "script-src 'self'") reads it into the same window.VEDETTA_* names as before and
    applies the theme and the view chosen before, before the first paint.
    python tests/check_page_boot.py"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from jinja2 import Environment, FileSystemLoader  # noqa: E402

from app import i18n  # noqa: E402

env = Environment(loader=FileSystemLoader(str(ROOT / "vedetta" / "app" / "templates")), autoescape=True)
env.globals.update(t=i18n.t, t_or=i18n.t_or, static_version=lambda p: "1")
env.filters.update(ago=lambda v: "", uptime=lambda v: "", uptime_short=lambda v: "")
STRINGS = {"js.ha.error.title": "Cannot load", "js.trap": "</script><script>alert(1)</script>"}
CTX = {"lang": "en", "lang_auto": True, "languages": [["en", "English"], ["it", "Italiano"]], "js_strings": STRINGS, "theme": "auto",
       "transparent": False, "compact": False, "limit": 6, "nonce": "n0nce"}

for base in ("", "/api/hassio_ingress/abc"):
    html = env.get_template("ha.html").render(**CTX, base=base)
    tags = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S)
    assert tags, "no script at all"
    for attrs, body in tags:
        runs = 'type="application/json"' not in attrs
        assert not (runs and body.strip()), "an inline script that must run: %r" % body[:80]
        assert not runs or "src=" in attrs, attrs
    blocks = [body for attrs, body in tags if 'id="vedetta-boot"' in attrs]
    assert len(blocks) == 1, "one block of start data"
    boot = json.loads(blocks[0])
    assert boot == {"base": base, "lang": "en", "lang_auto": True, "i18n": STRINGS, "langs": [["en", "English"], ["it", "Italiano"]]}, boot
    assert "</script><script>alert" not in html, "the data cannot close its block"
    srcs = re.findall(r'<script\b[^>]*\bsrc="([^"]+)"', html)
    assert srcs[0].startswith(base + "/static/ha/boot.js"), ("boot.js first, before every other file", srcs)
    head, body_part = html.split("</head>", 1)
    assert 'id="vedetta-boot"' in head and base + "/static/ha/boot.js" in head, "the data and boot.js in the head: the theme before the first paint"
    assert head.index('id="vedetta-boot"') < head.index("/static/ha/boot.js"), "the data before boot.js"
    assert ("/static/js/base.js" in html) == bool(base), "the wrapper of the prefix only under a prefix, as before"

# boot.js: run it for real (Node) against a fake page: the names of before, the theme and the view of before
BOOT = ROOT / "vedetta" / "app" / "static" / "ha" / "boot.js"
assert BOOT.exists(), BOOT
node = r"""
const fs = require("fs");
const attrs = {};
const data = JSON.stringify({ base: "/p", lang: "it", lang_auto: false, i18n: { a: "A" }, langs: [["it", "Italiano"]] });
global.document = { getElementById: (id) => (id === "vedetta-boot" ? { textContent: data } : null),
                    documentElement: { setAttribute: (k, v) => { attrs[k] = v; } } };
global.window = global;
global.location = { search: "" };
global.localStorage = { getItem: (k) => ({ "vedetta-ha-theme": "dark", "vedetta-ha-view": "list" })[k] || null };
eval(fs.readFileSync(process.argv[1], "utf8"));
console.log(JSON.stringify([window.VEDETTA_BASE, window.VEDETTA_LANG, window.VEDETTA_LANG_AUTO, window.VEDETTA_I18N, window.VEDETTA_LANGS, attrs]));
"""
try:
    out = subprocess.run(["node", "-e", node, str(BOOT)], capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    assert got == ["/p", "it", False, {"a": "A"}, [["it", "Italiano"]], {"data-theme": "dark", "data-view": "list"}], got
    print("ok: boot.js gives the names of before")
except FileNotFoundError:
    print("skipped: boot.js under Node (node not installed)")

print("check_page_boot OK")
