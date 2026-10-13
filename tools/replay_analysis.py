"""Replay of the analysis status (app/analysis/status.py) over real exports: how many cards would be identified, settling or under analysis, and why. Read-only; exports stay in
~/.vedetta/exports. The age of a card is the time between its first presence event and the last event of the export.
    python tools/replay_analysis.py [export.zip ...]"""
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
sys.path.insert(0, str(ROOT / "tools"))
from app.analysis import status  # noqa: E402
import replay_mac_sharing as sharing  # noqa: E402

BIG_AGE = 10 ** 9   # no history in the export: treated as old


def ages(path: Path) -> dict[str, float]:
    events = sharing.load_events(path)
    if not events:
        return {}
    last, first = max(e[3] for e in events), {}
    for device, _mac, _online, ts in events:
        first.setdefault(device, ts)
    return {device: last - ts for device, ts in first.items()}


def replay(path: Path) -> Counter:
    with zipfile.ZipFile(path) as z:
        if "state/evidence.json" not in z.namelist():
            print(f"== {path.name}: no evidence card in this export (older version), skipped")
            return Counter()
        evidence = json.loads(z.read("state/evidence.json"))
        debug = json.loads(z.read("state/devices_debug.json"))
    age = ages(path)
    states, reasons = Counter(), Counter()
    for card_id, card in evidence.items():
        sheet = debug.get(card_id, {})
        sheet = sheet.get("debug", sheet)
        scores = (sheet.get("type") or {}).get("scores") or {}
        result = status.assess(card.get("group", {}), age_s=age.get(card_id, BIG_AGE), scores=scores, chosen=card.get("group", {}).get("value"))
        states[result.state] += 1
        reasons.update(result.reasons)
    print(f"== {path.name}: {len(evidence)} cards -> {dict(states)}; reasons {dict(reasons)}")
    return states


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or sorted(sharing.EXPORTS.glob("*.zip"))
    total = Counter()
    for p in paths:
        total.update(replay(p))
    n = sum(total.values())
    print(f"\ntotal {n} cards: " + ", ".join(f"{k} {v} ({100 * v // n}%)" for k, v in total.items()))


if __name__ == "__main__":
    main(sys.argv[1:])
