"""Replay of the presence history of real exports through the two rules for a MAC "shared by several cards": the old one (the MAC appears under more than
one card in the window) against the new one (two cards used it at the same time, storage/overlap.py). Prints, per export, the MACs the two rules judge
differently and the cards whose count of private MACs changes. Read-only; the exports stay in ~/.vedetta/exports.
    python tools/replay_mac_sharing.py [export.zip ...]"""
import sqlite3
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app.storage import overlap  # noqa: E402

EXPORTS = Path.home() / ".vedetta" / "exports"


def load_events(path: Path) -> list[tuple]:
    """(device, mac, online, ts) of the presence history of an export, in time order; [] if the export has none."""
    with zipfile.ZipFile(path) as z:
        if "data/vedetta.db" not in z.namelist():
            return []
        db_path = Path(tempfile.mkdtemp(prefix="replay-")) / "db"
        db_path.write_bytes(z.read("data/vedetta.db"))
    rows = sqlite3.connect(db_path).execute("SELECT device_id, mac, online, ts FROM presence_events ORDER BY ts, id").fetchall()
    return [(d, (m or "").lower() or None, o, ts) for d, m, o, ts in rows]


def is_private(mac: str) -> bool:
    return bool(int(mac[:2], 16) & 2)


def owners(events) -> dict[str, set]:
    found = defaultdict(set)
    for device, mac, _online, _ts in events:
        if mac:
            found[mac].add(device)
    return found


def counts(events, lent: set) -> dict[str, int]:
    seen = {(d, m) for d, m, _o, _t in events if m}
    result: dict[str, int] = {}
    for device, mac in seen:
        if is_private(mac) and mac not in lent:
            result[device] = result.get(device, 0) + 1
    return result


def replay(path: Path) -> tuple[int, int, int]:
    events = load_events(path)
    if not events:
        return 0, 0, 0
    old_lent = {m for m, devices in owners(events).items() if len(devices) > 1}
    new_lent = overlap.shared_macs(events, max(e[3] for e in events))
    old_counts, new_counts = counts(events, old_lent), counts(events, new_lent)
    changed = {d: (old_counts.get(d, 0), new_counts.get(d, 0)) for d in set(old_counts) | set(new_counts) if old_counts.get(d, 0) != new_counts.get(d, 0)}
    print(f"== {path.name}: {len(events)} events, {len(owners(events))} MACs; shared old {len(old_lent)}, new {len(new_lent)}")
    for mac in sorted(old_lent ^ new_lent):
        print(f"   {mac[:8]}..: {'shared' if mac in old_lent else 'not shared'} -> {'shared' if mac in new_lent else 'not shared'} ({len(owners(events)[mac])} cards)")
    for device, (before, after) in sorted(changed.items()):
        print(f"   card {device}: private MACs {before} -> {after}")
    return len(old_lent ^ new_lent), len(changed), len(events)


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or sorted(EXPORTS.glob("*.zip"))
    totals = [replay(p) for p in paths]
    print(f"\nexports with history: {sum(1 for t in totals if t[2])} of {len(totals)}; MACs judged differently: {sum(t[0] for t in totals)}; cards changed: {sum(t[1] for t in totals)}")


if __name__ == "__main__":
    main(sys.argv[1:])
