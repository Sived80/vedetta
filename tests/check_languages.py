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


TONIGHT = {"en": "tonight", "it": "stanotte", "de": "heute nacht", "cs": "dnes v noci", "fr": "cette nuit"}   # the word for «tonight» of each language
en = load("en")
codes = sorted(p.name for p in LOC.iterdir() if p.is_dir())
config = (ROOT / "vedetta" / "config.yaml").read_text(encoding="utf-8")
check("language" not in re.findall(r"^\s+([a-z_]+):", config, re.M), "config.yaml has no language option: the page follows Home Assistant, each person picks theirs in the menu")
docs = (ROOT / "vedetta" / "DOCS.md").read_text(encoding="utf-8")
check("en" in codes, "English is there: it is the base the others are measured on")
for code in codes:
    tr = load(code)
    check(bool(tr.get("server.json:lang.name")), f"{code}: names itself (lang.name)")
    check(bool(tr.get("ha.json:js.ha.menu.lang_auto")), f"{code}: translates the 'Automatic' entry of the language list")
    check(f"`{code}`" in docs, f"{code}: is named in DOCS.md")
    # a plural form English does not need (Czech «_few», 2 to 4) belongs to a text English has, with the same placeholders
    # (the English text is the key itself, or its «_other» form)
    plural = {}
    for k in tr:
        if re.search(r"_(few|many)$", k) and k not in en:
            stem = re.sub(r"_(few|many)$", "", k)
            plural[k] = next((b for b in (stem + "_other", stem) if b in en), None)
    stray = [k for k in tr if k not in en and not plural.get(k)]
    check(not stray, f"{code}: no key that English does not have {stray[:3]}")
    bad = [k for k in tr if k in en and holes(tr[k]) != holes(en[k])] + [k for k, base in plural.items() if base and holes(tr[k]) != holes(en[base])]
    check(not bad, f"{code}: placeholders match the English text {bad[:3]}")
    # one name for the deep search (19/11 review): the texts that name it use the words of its title, never a second name for it
    term = (tr.get("ha.json:js.ha.deep.title") or "").lower()
    named = ["js.ha.attr.scanned", "js.ha.attr.scanned_empty", "js.ha.deep.done", "js.ha.deep.note", "js.ha.deep.busy", "js.ha.ev.g.none"]
    other = [k for k in named if "ha.json:" + k in tr and term not in tr["ha.json:" + k].lower()]
    check(bool(term) and not other, f"{code}: the deep search has one name, the one of its title {other[:3]}")
    # the automatic deep search starts at night: the note says «tonight», not «today»
    tonight = TONIGHT.get(code)
    check(not tonight or tonight in (tr.get("ha.json:js.ha.deep.note") or "").lower(), f"{code}: the note of the deep search says it starts tonight")
    missing = len([k for k in en if k not in tr])
    print(f"info: {code}: {len(tr)} of {len(en)} texts translated ({missing} missing, English is shown for those)")
print("ALL OK" if not failed else f"FAILED: {failed}")
sys.exit(1 if failed else 0)
