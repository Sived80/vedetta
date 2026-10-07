"""Replay of real exports through the group classifier: a git revision (default origin/main) against the working copy.

    python tools/replay_exports.py                      # every export in ~/.vedetta/exports
    python tools/replay_exports.py report.txt other.zip # these files
    python tools/replay_exports.py --base 9fbd711       # compare with another revision
    python tools/replay_exports.py --all                # also the devices whose group does not change

Prints the devices whose group changes (name, address, group in the export, before, after). Nothing is written to disk: the
export is read in memory and the old code is extracted to a temporary folder that is deleted. The exports are not in the
repository (they are the data of the users); they are kept in ~/.vedetta/exports.
A card is rebuilt from what the export holds (attributes, ports, Home Assistant registry); a device the export does not describe
enough (the kinds of entities of older exports) is rebuilt with an assumption: no named entity = only a tracker."""
import argparse
import importlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import riepilogo_report as rr  # noqa: E402


def load_ha_data(root: Path):
    for m in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[m]
    sys.path.insert(0, str(root))
    try:
        try:
            return importlib.import_module("app.ha.ha_data")
        except ImportError:                      # a revision from before the modules were put in packages
            return importlib.import_module("app.ha_data")
    finally:
        sys.path.pop(0)


def build(card: dict, registry: dict, with_entity_kinds: bool) -> tuple[dict, str | None]:
    extra = {a["key"]: a["value"] for a in card.get("attrs") or [] if isinstance(a.get("value"), str)}
    mac = (card.get("mac") or "").lower()
    ha = (registry.get("by_mac") or {}).get(mac) or (registry.get("by_ip") or {}).get(card.get("ip"))
    if ha:
        ha = dict(ha)
        extra["ha_integration"] = ", ".join(ha.get("domains") or [])      # as the app writes it (the export masks the text)
        if ha.get("model"):
            extra["ha_model"] = ha["model"]
        if with_entity_kinds and "entity_domains" not in ha:
            ha["entity_domains"] = ["device_tracker", "sensor"] if ha.get("entity_names") else ["device_tracker"]
    dev = {"id": card["id"], "ip": card["ip"], "name": card["name"], "brand": card.get("brand"), "vendor": card.get("vendor"),
           "vendor_role": card.get("vendor_role"), "extra": extra, "scanned_ports": card.get("ports") or [], "ha_registry": ha,
           "is_mobile": card.get("is_mobile")}
    adapter = "shelly" if card.get("brand") == "Shelly" and card.get("name_source") == "adapter" else None
    return dev, adapter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    files = [Path(f) for f in args.files] or sorted((Path.home() / ".vedetta" / "exports").glob("*"))
    if not files:
        print("no exports found")
        return 1
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:   # (on Windows the old code may still hold its database open)
        data = subprocess.run(["git", "archive", args.base, "vedetta/app"], cwd=ROOT, capture_output=True, check=True).stdout
        tar = Path(tmp) / "old.tar"
        tar.write_bytes(data)
        with tarfile.open(tar) as t:
            t.extractall(tmp)
        old = load_ha_data(Path(tmp) / "vedetta")
        new = load_ha_data(ROOT / "vedetta")
        total = changed = 0
        for f in files:
            z = rr.load_zip(f, None)
            cards = json.loads(z.read("state/devices_compact.json"))
            registry = json.loads(z.read("state/ha_registry.json")) if "state/ha_registry.json" in z.namelist() else {}
            print("== %s: %d devices" % (f.name, len(cards)))
            for c in cards:
                d0, a = build(c, registry, False)
                d1, _ = build(c, registry, True)
                g_old, g_new = old.infer_type(d0, a), new.infer_type(d1, a)
                total += 1
                if g_old != g_new or args.all:
                    changed += g_old != g_new
                    print("  %-24s %-15s export=%-8s %-8s -> %s%s" % (c["name"][:24], c["ip"], c.get("type"), g_old, g_new, "" if g_old == g_new else "   <--"))
        print("\ndevices: %d, group changed: %d" % (total, changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
