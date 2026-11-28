# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The window that ignores a device says where to restore it: in every language it names the menu item Networks and its section
Ignored devices, with the same words as the page (js.networks.ui.title, js.networks.ui.sec_ignored). It said "the classic dashboard",
a page that no longer exists (discussion #69). No text of any language speaks of that page any more.
    python tools/run_test.py check_ignore_text_points_to_networks.py"""
import json
import sys
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "locales"
OLD_PAGE = ("classic dashboard", "dashboard classica", "klassische dashboard", "klasick", "tableau de bord classique")

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


langs = sorted(p.name for p in LOCALES.iterdir() if p.is_dir())
check(set(langs) >= {"en", "it", "de", "cs", "fr"}, "the five languages are there: %s" % langs)
for lang in langs:
    texts = {}
    for f in (LOCALES / lang).glob("*.json"):
        texts.update(json.loads(f.read_text(encoding="utf-8")))
    ignore = texts.get("js.ha.ignore.text", "")
    check(texts["js.networks.ui.title"] in ignore and texts["js.networks.ui.sec_ignored"] in ignore,
          "%s: the ignore window names Networks and Ignored devices: %s" % (lang, ascii(ignore)))   # ascii: any console
    stale = [k for k, v in texts.items() if any(w in v.lower() for w in OLD_PAGE)]
    check(not stale, "%s: no text speaks of the classic dashboard (%s)" % (lang, ", ".join(stale) or "none"))

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
