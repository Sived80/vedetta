"""Every language folder is complete enough to be offered: it names itself, it is in the options of the app and in the documentation, it
has no key English does not have, and its placeholders match the English text. Missing keys are only reported (English fills the gap)."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOC = ROOT / "vedetta" / "app" / "locales"
failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("ok:", msg)
    else:
        failed += 1
        print("FAILED:", msg)


def load(code):
    out = {}
    for f in sorted((LOC / code).glob("*.json")):
        for k, v in json.loads(f.read_text(encoding="utf-8")).items():
            out[f"{f.name}:{k}"] = v
    return out


def holes(text):
    return sorted(re.findall(r"\{[a-z_0-9]+\}|%[sd]", text)) if isinstance(text, str) else []


en = load("en")
codes = sorted(p.name for p in LOC.iterdir() if p.is_dir())
config = (ROOT / "vedetta" / "config.yaml").read_text(encoding="utf-8")
schema = re.search(r"^\s+language: list\(([^)]*)\)", config, re.M)
offered = schema.group(1).split("|") if schema else []
docs = (ROOT / "vedetta" / "DOCS.md").read_text(encoding="utf-8")
check("en" in codes, "English is there: it is the base the others are measured on")
for code in codes:
    tr = load(code)
    check(bool(tr.get("server.json:lang.name")), f"{code}: names itself (lang.name)")
    check(code in offered, f"{code}: is in the language option of config.yaml ({'|'.join(offered)})")
    check(bool(tr.get("ha.json:js.ha.menu.lang_auto")), f"{code}: translates the 'Automatic' entry of the language list")
    check(f"`{code}`" in docs, f"{code}: is named in DOCS.md")
    stray = [k for k in tr if k not in en]
    check(not stray, f"{code}: no key that English does not have {stray[:3]}")
    bad = [k for k in tr if k in en and holes(tr[k]) != holes(en[k])]
    check(not bad, f"{code}: placeholders match the English text {bad[:3]}")
    missing = len([k for k in en if k not in tr])
    print(f"info: {code}: {len(tr)} of {len(en)} texts translated ({missing} missing, English is shown for those)")
check("auto" in offered and sorted(c for c in offered if c != "auto") == sorted(codes), "the options of config.yaml are `auto` plus exactly the folders of locales")
print("ALL OK" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
