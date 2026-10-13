"""Writes docs/ARCHITECTURE.md: the guide for a person who opens the code for the first time (what to read first, the rule of the layers, how one check of the network flows, where
to change what) and the index of every module with the first sentence of its docstring. The index and the layers are GENERATED from the code, so they cannot drift;
tests/check_architecture_doc.py fails when the file is not what this script writes.
    python tools/make_architecture.py [--write]"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "vedetta" / "app"
OUT = REPO / "docs" / "ARCHITECTURE.md"

INTRO = """# Architecture — a map for someone opening the code for the first time

[← Back to the README](../README.md) · [Development](DEVELOPMENT.md) · [How it works](HOW_IT_WORKS.md)

This page is written to be read in ten minutes. The index at the end is generated from the code (the first sentence of each module's docstring), so it is always current.

## Start here

1. Read [`vedetta/app/main.py`](../vedetta/app/main.py): it starts everything (`lifespan`) and mounts the routes. Nothing imports it except the tests.
2. Read [`vedetta/app/state.py`](../vedetta/app/state.py): `DeviceState` keeps the card of every device and drives the periodic check; the work itself is in `state_cycle.py` and `state_support.py`.
3. Read [`vedetta/app/scan/probe.py`](../vedetta/app/scan/probe.py): `probe_device` builds the card of ONE device. Names, web addresses and the pipeline of a deep search are in `probe_names.py`, `probe_web.py` and `pipeline.py`.
4. Recognition is **data**: `vedetta/app/data/*.json` (signatures, brands, device kinds). Teaching it a new device usually needs no code (see [Development](DEVELOPMENT.md)).

## The rule of the layers

A module may import from its own layer or from a lower one, never from a higher one. `tests/check_structure.py` enforces it (and forbids import cycles), so the dependencies always point down:

{LAYERS}

`main` is the top: it wires the routes and starts the service. Routes call everything below them and nothing but `main` calls a route.

## How one check of the network flows

1. `main.lifespan` starts the background work: it loads the history, starts the state loop, the nightly maintenance, the DHCP listener, the Home Assistant registry reader, the Bonjour listener, MQTT and the network-role watcher.
2. Every cycle `state_cycle.poll_once` loads the saved devices (`devices.yaml`), starts the ARP view and a response-time measurement, and asks `probe.probe_device` about every device in parallel.
3. `probe_device` asks the device's adapter (is it online?), adds what the earlier searches saved (`scan_info`), what Bonjour and DHCP remember and what Home Assistant knows, and decides the name, the brand and whether it is a phone. It returns one record; it only reads, it never changes anything on the network.
4. `state_cycle.settle` decides online or offline (a missed check is tolerated for a while), and `state_cycle.publish` stores the card and emits an event only if the card changed; the browsers receive it through server-sent events (see `sse.py`).
5. After the cycle: changed addresses are followed, duplicate phones merged, address conflicts reported, new devices announced, and the MAC layer (`maclayer.py`) records which MAC answered at which address. The MAC layer only records: nothing reads it yet.
6. A **deep search** (the button, or the night) is `scan/rescan.py`: it runs the deep profile of `pipeline.py` (ports, services, names, certificates), saves the result with its history, warns about ports that opened or closed, and applies a better name if one was found.

## Where to change what

| I want to… | Look at |
|---|---|
| teach it a device or a brand | `vedetta/app/data/signatures.json`, `brands.json`; the tests check it |
| change how a name or a brand is chosen | `scan/probe_names.py`, `recognition/naming.py`, `recognition/identity.py` |
| add or change a page of the web interface | `vedetta/app/frontend/` (ES modules in `js/`, the style in parts joined by `assets.py`), `routes/ha.py` |
| add an API route | `routes/` (one module per theme), wired in `main.py` |
| add or change a step of the search | `scan/flows.py` and `scan/pipeline_plan.py` (which steps run), `scan/pipeline_probes.py` (what each one does) |
| change what is exported for analysis | `export/` (`export_engine.py` is the entry, `anonymize.py` hides the personal data) |
| change what is saved | `storage/` (`history*.py` is the SQLite database, `devices_config.py` the device list) |

## Safety net

The functions that were restructured have a reference test that was generated from the code *before* the change (`tests/check_*_golden.py`, files in `tests/golden/`), so a change that alters their behaviour fails a test. `python tools/gate.py` runs all of them plus the complexity and structure checks. `python tools/readability.py` measures how easy the code is to read.

## Index of the modules

{INDEX}
"""


def literal_dict(tree: ast.Module, name: str) -> dict:
    for n in tree.body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return ast.literal_eval(n.value)
    return {}


def layers_block() -> str:
    tree = ast.parse((REPO / "tests" / "check_structure.py").read_text(encoding="utf-8"))
    root, pkg, mod = literal_dict(tree, "ROOT_LAYER"), literal_dict(tree, "PKG_LAYER"), literal_dict(tree, "MOD_LAYER")
    by = {}
    for k, v in root.items():
        by.setdefault(v, []).append("`%s`" % k)
    for k, v in pkg.items():
        by.setdefault(v, []).append("`%s/`" % k)
    lines = []
    for lvl in sorted(by):
        lines.append("- **layer %d**: %s" % (lvl, ", ".join(sorted(by[lvl]))))
    lines.append("")
    lines.append("A few modules sit at another layer than their folder (for example `scan/dhcp.py` and `scan/mdns_listener.py` are base modules that import only the standard library); they are listed by name in `tests/check_structure.py`.")
    return "\n".join(lines)


def first_sentence(doc: str) -> str:
    text = " ".join(doc.strip().split("\n\n")[0].split())
    cut = text.find(". ")
    text = text[:cut + 1] if cut != -1 else text
    return text.replace("|", "\\|")


def index_block() -> str:
    groups = {}
    for f in sorted(APP.rglob("*.py")):
        if "__pycache__" in f.parts or f.name == "__init__.py":
            continue
        rel = f.relative_to(APP)
        doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8"))) or ""
        groups.setdefault(rel.parts[0] if len(rel.parts) > 1 else "(top level)", []).append((str(rel).replace("\\", "/"), first_sentence(doc)))
    out = []
    for g in sorted(groups, key=lambda k: (k != "(top level)", k)):
        out.append("### %s" % (g if g == "(top level)" else g + "/"))
        out.append("")
        out.append("| module | what it is for |")
        out.append("|---|---|")
        for rel, s in groups[g]:
            out.append("| `%s` | %s |" % (rel, s or "—"))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def first_comment(path: Path) -> str:
    """The first line of comment of a front-end part, without the comment marks and the separators."""
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip().lstrip("/*").strip().rstrip("*/").strip().strip("-").strip()
        if line.strip().startswith(("//", "/*")) and s:
            return s.replace("|", "\\|")[:140]
    return "-"


def frontend_block() -> str:
    folder = APP / "frontend" / "ha"
    out = ["### frontend/ha (the page /ha)", "",
           "The files of `js/` are ES modules: the page loads `js/app.js` and the browser follows the imports; each module imports what it uses of the others and exports what the others use, and `core.js` is the base (it imports nothing). `css/` is joined in name order into ha.css by `assets.py`.", "",
           "| part | lines | what it is for |", "|---|---|---|"]
    for kind in ("js", "css"):
        for f in sorted((folder / kind).glob("*." + kind)):
            out.append("| `%s/%s` | %d | %s |" % (kind, f.name, len(f.read_text(encoding="utf-8", errors="ignore").splitlines()), first_comment(f)))
    return "\n".join(out) + "\n"


def render() -> str:
    return INTRO.replace("{LAYERS}", layers_block()).replace("{INDEX}", index_block() + "\n" + frontend_block())


if __name__ == "__main__":
    text = render()
    if "--write" in sys.argv:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print("written", OUT.relative_to(REPO), len(text.splitlines()), "lines")
    else:
        print(text[:1500])
    print("DONE_ARCH")
