"""Does a simulated network behave like the real one? The measures are taken on what a host of the LAN sees (which MAC answers for each address, cycle after
cycle) and compared with the thresholds written, before the simulator existed, in the specification sheet (taken from a real export: 7 days of presence)."""
from collections import Counter, defaultdict
from dataclasses import dataclass

# name -> (lowest, highest) accepted
THRESHOLDS = {
    "extender_share": (0.85, 1.0),          # real: 351 of 370 changes involve the extender
    "symmetry": (0.0, 0.10),                # real: 176 towards the extender, 175 away from it
    "top3_share": (0.70, 1.0),              # real: three addresses make 309 of the 370 changes
    "extender_address_share": (0.5, 1.0),   # real: the extender shows up on 10 of the 13 addresses that change
    "stay_p10": (1, 3),                     # real: 2 cycles on the busiest address
    "stay_p50": (3, 15),                    # real: 9 cycles on the busiest address
    "macs_min": (2, 6),                     # real: 2 to 6 MACs on an address of a phone
    "macs_max": (2, 6),
    "bounce_share": (0.03, 0.20),           # real: 9 % of the changes follow the previous one within one cycle
}


@dataclass(frozen=True)
class Observation:
    cycle: int
    ip: str
    mac: str


@dataclass(frozen=True)
class Flip:
    cycle: int
    ip: str
    old: str
    new: str


def flips(observations: list[Observation]) -> list[Flip]:
    """Every time the MAC that answers for an address is not the one of the previous observation of that address."""
    last: dict[str, Observation] = {}
    found = []
    for o in sorted(observations, key=lambda o: (o.cycle, o.ip)):
        before = last.get(o.ip)
        if before and before.mac != o.mac:
            found.append(Flip(o.cycle, o.ip, before.mac, o.mac))
        last[o.ip] = o
    return found


def _quantile(values: list[int], p: float) -> int | None:
    return sorted(values)[min(len(values) - 1, int(p * len(values)))] if values else None


def _stays(found: list[Flip], extender: str) -> list[int]:
    """How many cycles the extender kept an address: from the change to it to the next change on that address."""
    per_ip = defaultdict(list)
    for f in found:
        per_ip[f.ip].append(f)
    return [b.cycle - a.cycle for seq in per_ip.values() for a, b in zip(seq, seq[1:]) if a.new == extender]


def _bounces(found: list[Flip]) -> int:
    per_ip = defaultdict(list)
    for f in found:
        per_ip[f.ip].append(f.cycle)
    return sum(1 for cycles in per_ip.values() for a, b in zip(cycles, cycles[1:]) if b - a <= 1)


def summarize(observations: list[Observation], extender: str) -> dict:
    """The measures of a timeline; `extender` is the MAC of the Wi-Fi extender."""
    found = flips(observations)
    with_ext = [f for f in found if extender in (f.old, f.new)]
    to_ext, from_ext = sum(f.new == extender for f in with_ext), sum(f.old == extender for f in with_ext)
    per_ip = Counter(f.ip for f in found)
    macs = defaultdict(set)
    for o in observations:
        macs[o.ip].add(o.mac)
    macs_per_address = {ip: len(macs[ip]) for ip in per_ip}
    ext_addresses = {f.ip for f in with_ext}
    stays = _stays(found, extender)
    return {
        "flips": len(found),
        "extender_share": len(with_ext) / len(found) if found else 0.0,
        "symmetry": abs(to_ext - from_ext) / len(with_ext) if with_ext else 1.0,
        "top3_share": sum(n for _, n in per_ip.most_common(3)) / len(found) if found else 0.0,
        "extender_addresses": len(ext_addresses),
        "extender_address_share": len(ext_addresses) / len(per_ip) if per_ip else 0.0,
        "stays": stays,
        "stay_p10": _quantile(stays, 0.1), "stay_p50": _quantile(stays, 0.5), "stay_p90": _quantile(stays, 0.9),
        "macs_per_address": macs_per_address,
        "macs_min": min(macs_per_address.values(), default=None), "macs_max": max(macs_per_address.values(), default=None),
        "bounce_share": _bounces(found) / len(found) if found else 0.0,
    }


def compare(summary: dict) -> list[dict]:
    """One row per threshold: the measured value, the accepted range and whether it fits (a missing value does not)."""
    rows = []
    for name, (low, high) in THRESHOLDS.items():
        value = summary.get(name)
        rows.append({"name": name, "value": value, "low": low, "high": high, "ok": value is not None and low <= value <= high})
    return rows
