"""The words that are at the same time the name of a maker and a word of function, found in the data files (not written by hand), and what has been decided about each (tests/data/word_collisions.json).

    python tools/word_collisions.py            the collisions, with the decision of each and the ones still undecided
    python tools/word_collisions.py --json     the same as JSON

A collision is a whole name (brands.json aliases, brand_logos.json names, the "brands" of the types of device_kinds.json) that is also a whole word of a type (device_kinds.json words and tokens) or of a group
(type_words.json). Why it matters: a word that tells who made a device must not tell what it does when the two differ ("Tenda" is a maker of routers, "tenda" a curtain). Each collision gets ONE decision:
  same       the maker and the word point to the same thing (Epson, printer)
  multi      the maker makes several kinds of device: the word is only a weak prior
  different  a homonym: the word of function is NOT what the maker makes; it needs a fence ("dual": the data/brands.json role that keeps the maker's name out of the words of function)
A new collision without a decision fails the test (tests/check_word_collisions.py): adding a brand or a word makes someone decide."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "vedetta" / "app" / "data"
DECISIONS = ROOT / "tests" / "data" / "word_collisions.json"


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


def _read(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def makers() -> dict[str, set[str]]:
    """Every whole name of a maker, with where it comes from."""
    found: dict[str, set[str]] = {}

    def add(name, source):
        if _norm(name):
            found.setdefault(_norm(name), set()).add(source)

    for alias in _read("brands.json")["aliases"]:
        for name in alias:
            add(name, "brands.aliases")
    for logo in _read("brand_logos.json")["logos"]:
        for name in [logo.get("id", "")] + list(logo.get("names", [])):
            add(name, "brand_logos")
    for kind in _read("device_kinds.json")["kinds"]:
        for name in kind.get("brands", []):
            add(name, "kinds.brands:" + kind["id"])
    return found


def function_words() -> dict[str, set[str]]:
    """Every whole word of a type or of a group, with where it comes from."""
    found: dict[str, set[str]] = {}
    for kind in _read("device_kinds.json")["kinds"]:
        for word in kind.get("words", []) + kind.get("tokens", []):
            found.setdefault(_norm(word), set()).add("kind:" + kind["id"])
    for group, rules in _read("type_words.json")["groups"].items():
        for word in list(rules["subs"]) + list(rules["toks"]):
            found.setdefault(_norm(word), set()).add("group:" + group)
    return found


def collisions() -> dict[str, dict]:
    maker, words = makers(), function_words()
    return {name: {"makers": sorted(maker[name]), "words": sorted(words[name])} for name in sorted(maker) if name in words}


def decisions() -> dict[str, dict]:
    return json.loads(DECISIONS.read_text(encoding="utf-8"))["decisions"] if DECISIONS.exists() else {}


def undecided(found: dict, decided: dict) -> list[str]:
    return [name for name in found if name not in decided]


def stale(found: dict, decided: dict) -> list[str]:
    return [name for name in decided if name not in found]


def main() -> int:
    found, decided = collisions(), decisions()
    if "--json" in sys.argv:
        print(json.dumps({"collisions": found, "undecided": undecided(found, decided), "stale": stale(found, decided)}, indent=1))
        return 0
    for name, row in found.items():
        print("%-16s %-10s makers %-48s words %s" % (name, (decided.get(name) or {}).get("meaning", "?"), ",".join(row["makers"]), ",".join(row["words"])))
    print("\n%d collisions, %d undecided, %d stale decisions" % (len(found), len(undecided(found, decided)), len(stale(found, decided))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
