"""Compare two exports of Vedetta taken on the same network (for example the real app and the debug copy): what each one knows about the same devices.
  python tools/compare_exports.py A.zip B.zip [--label-a produzione] [--label-b debug] [--all]
Devices are matched by MAC (else by address) - so take both exports "for me" (not masked), otherwise the numbered placeholders differ between the two files.
Prints: versions and counts, the devices only one of the two sees, and for the devices both see the fields that differ (name and where it came from, brand, group, mobile,
the certainty of each as the evidence sheet gives it). --all also lists the fields that are the same. Nothing is written."""
import argparse
import json
import sys
import zipfile
from pathlib import Path

FIELDS = ("name", "name_source", "brand", "brand_source", "type", "is_mobile", "vendor", "online", "mac", "ip")
CERTAINTY = (("name", "name"), ("brand", "brand"), ("group", "type"))


def load(path: Path) -> dict:
    z = zipfile.ZipFile(path)
    names = z.namelist()
    cards = json.loads(z.read("state/devices_compact.json"))
    evidence = json.loads(z.read("state/evidence.json")) if "state/evidence.json" in names else {}
    manifest = json.loads(z.read("manifest.json")) if "manifest.json" in names else {}
    return {"cards": cards, "evidence": evidence, "manifest": manifest}


def key_of(card: dict) -> str:
    mac = (card.get("mac") or "").lower()
    return mac or f"ip:{card.get('ip')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()
    A, B = load(Path(args.a)), load(Path(args.b))
    la, lb = args.label_a, args.label_b
    for lab, d in ((la, A), (lb, B)):
        m = d["manifest"]
        print(f"{lab}: version {m.get('version')} | export for: {m.get('dest')} | created {m.get('created')} | devices {len(d['cards'])}")
    if A["manifest"].get("dest") != B["manifest"].get("dest") or "dev" in (A["manifest"].get("dest"), B["manifest"].get("dest")):
        print("WARNING: the exports are not both 'for me' (unmasked): addresses and names may be placeholders that cannot be matched")
    ca = {key_of(c): c for c in A["cards"]}
    cb = {key_of(c): c for c in B["cards"]}
    only_a, only_b = sorted(set(ca) - set(cb)), sorted(set(cb) - set(ca))
    both = sorted(set(ca) & set(cb))
    print(f"\nboth see {len(both)} devices; only {la}: {len(only_a)}; only {lb}: {len(only_b)}")
    for lab, only, src in ((la, only_a, ca), (lb, only_b, cb)):
        for k in only:
            c = src[k]
            print(f"  only {lab}: {c.get('name')} ({c.get('ip')}, {c.get('mac')}, {c.get('type')})")
    diffs = 0
    print()
    for k in both:
        x, y = ca[k], cb[k]
        ex, ey = A["evidence"].get(x.get("id"), {}), B["evidence"].get(y.get("id"), {})
        rows = []
        for f in FIELDS:
            if x.get(f) != y.get(f):
                rows.append(f"{f}: {x.get(f)!r} | {y.get(f)!r}")
            elif args.all:
                rows.append(f"{f}: same ({x.get(f)!r})")
        for label, _f in CERTAINTY:
            cx, cy = (ex.get(label) or {}).get("certainty"), (ey.get(label) or {}).get("certainty")
            if cx != cy:
                rows.append(f"certainty of {label}: {cx} | {cy}")
        real = [r for r in rows if not r.endswith(")") or "same" not in r]
        if real:
            diffs += 1
        if rows and (real or args.all):
            print(f"{x.get('name')} ({x.get('ip')})")
            for r in rows:
                print("   ", r)
    print(f"\ndevices with differences: {diffs} of {len(both)} (left of the bar: {la}, right: {lb})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
