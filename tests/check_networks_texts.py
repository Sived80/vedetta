# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The texts of the panel «Networks» (locales/<lang>/netpanel.json): every key the judge may need (networks/caps.text_keys) and every key the page
asks by name (frontend/ha/js/netpanel.js) is there in English, Italian, German and Czech, with the same placeholders, and is short (one sentence
per line: no text over MAX characters). No text names the routers' other menus ("Su altri router") or says how many ways there are ("Basta una"):
rules of the owner for «Come attivarlo».
    python tests/check_networks_texts.py"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app.networks import caps  # noqa: E402

LANGS = ("en", "it", "de", "cs")
MAX = 200
PAGE = ROOT / "vedetta" / "app" / "frontend" / "ha" / "js" / "netpanel.js"
MENU = PAGE.parent / "core-menu.js"
tables = {lang: json.loads((ROOT / "vedetta" / "app" / "locales" / lang / "netpanel.json").read_text(encoding="utf-8")) for lang in LANGS}
SRC = PAGE.read_text(encoding="utf-8")
asked = {"js.networks." + k for k in re.findall(r'\bT\("([a-z0-9_.]*[a-z0-9])"', SRC)}          # T("ui.add"): the page's own helper
asked |= set(re.findall(r'"(js\.networks\.[a-z0-9_.]*[a-z0-9])"', SRC + MENU.read_text(encoding="utf-8")))
asked |= {"js.networks.ui.%s_%s" % (p, s) for p in ("state", "bar") for s in ("on", "new", "mute", "paused", "how", "soon", "off") if "js.networks.ui.%s_%s" % (p, s) in tables["en"]}
needed = set(caps.text_keys()) | asked
needed |= {k for k in tables["en"] if k.endswith("_one") and k[:-4] in needed}      # the singular of a text with {n} (t() picks it for n == 1)
assert asked, "the page asks its texts by name"
failed = []
for lang, table in tables.items():
    failed += ["%s: missing %s" % (lang, k) for k in sorted(needed - set(table))]
    # a plural form English does not need (Czech «_few», 2 to 4) is allowed when English has the text it belongs to
    plural = {k: re.sub(r"_(few|many)$", "", k) for k in table if re.search(r"_(few|many)$", k) and k not in tables["en"]}
    failed += ["%s: not in English %s" % (lang, k) for k in sorted(set(table) - set(tables["en"])) if plural.get(k) not in tables["en"]]
    for key, text in table.items():
        if not key.startswith("js.networks."):
            failed.append("%s: %s is not a key of the panel" % (lang, key))
        if sorted(re.findall(r"\{\w+\}", text)) != sorted(re.findall(r"\{\w+\}", tables["en"].get(plural.get(key, key), text))):
            failed.append("%s: other placeholders in %s" % (lang, key))
        if len(text) > MAX or re.search(r"altri router|basta una|other routers|just one of", text, re.I):
            failed.append("%s: %s is too long or says what the owner does not want" % (lang, key))
unused = set(tables["en"]) - needed - {k for k in tables["en"] if re.match(r"js\.networks\.(capd|ui)\.", k)}
failed += ["unused: %s" % k for k in sorted(unused)]
assert not failed, "\n".join(failed)
print("check_networks_texts: ok (%d keys, %d asked by the page)" % (len(tables["en"]), len(asked)))
