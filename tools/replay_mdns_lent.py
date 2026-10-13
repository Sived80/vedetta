"""Replay of the mDNS memory of real exports with and without the rule «a MAC lent to several cards names none of them» (scan/mdns_listener.py).
For every card of an export the memory is looked up as before and as now; where the answer changes it prints what the card lost and what the stored
"mobile" score would become (the mobile service of a neighbour is worth +3, probe.py). The lent MACs come from the presence history of the export
(storage/overlap.py), the closest thing an export holds to the ARP view of the moment.
    python tools/replay_mdns_lent.py [export.zip ...]"""
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
sys.path.insert(0, str(ROOT / "tools"))
from app.scan import mdns_listener as ml  # noqa: E402
from app.scan.probe import _MOBILE_SERVICES  # noqa: E402
import replay_mac_sharing as sharing  # noqa: E402
from app.storage import overlap  # noqa: E402

MOBILE_THRESHOLD, MOBILE_SERVICE_POINTS = 3, 3


def load(path: Path) -> tuple[dict, dict, list]:
    """(mdns memory, cards by id, debug sheets) of an export."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        memory = json.loads(z.read("state/mdns_seen.json")) if "state/mdns_seen.json" in names else {}
        cards = {d["id"]: d for d in json.loads(z.read("state/devices_compact.json"))}
        debug = json.loads(z.read("state/devices_debug.json")) if "state/devices_debug.json" in names else {}
    return memory, cards, debug


def services(card) -> set:
    return set((card or {}).get("services") or [])


def replay(path: Path) -> int:
    memory, cards, debug = load(path)
    events = sharing.load_events(path)
    lent = overlap.shared_macs(events, max(e[3] for e in events)) if events else set()
    ml.by_mac.clear()
    ml.by_ip.clear()
    ml.by_mac.update(memory.get("by_mac") or {})
    ml.by_ip.update(memory.get("by_ip") or {})
    changed = 0
    for card_id, card in cards.items():
        mac = (card.get("mac") or "").lower()
        ml._is_lent_mac = lambda m: False
        before = ml.lookup(mac, card["ip"])
        ml._is_lent_mac = lambda m: m in lent
        after = ml.lookup(mac, card["ip"])
        if before == after:
            continue
        changed += 1
        lost = services(before) - services(after)
        mobile = bool(lost & _MOBILE_SERVICES)
        sheet = (debug.get(card_id) or {}).get("debug") or debug.get(card_id) or {}
        score = (sheet.get("mobile") or {}).get("score")
        new_score = None if score is None else score - (MOBILE_SERVICE_POINTS if mobile else 0)
        verdict = "" if score is None else f" mobile score {score} -> {new_score}" + (" (stops being mobile)" if score >= MOBILE_THRESHOLD > new_score else "")
        print(f"   {card['ip']:<16} {card.get('type') or '-':<8} memory of address {before.get('ip') if before else None} -> "
              f"{after.get('ip') if after else None}; services lost {sorted(lost)}{verdict}")
    print(f"== {path.name}: {len(cards)} cards, {len(lent)} lent MACs, {changed} lookups changed")
    return changed


def main(argv: list[str]) -> None:
    paths = [Path(a) for a in argv] or sorted(sharing.EXPORTS.glob("*.zip"))
    print("lookups changed in total:", sum(replay(p) for p in paths if p.suffix == ".zip"))


if __name__ == "__main__":
    main(sys.argv[1:])
