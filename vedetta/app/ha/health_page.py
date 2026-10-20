"""The network-health findings as the page draws them: who (the name and the IP of each device; the MAC only for a device that has no card, the one thing that tells it apart), what (the rule and its counts), when (first and last sight) and how many times.
Pure: the findings, the device cards, the IP conflicts of the scan and the address of the gateway are handed in. Only the active findings are drawn, one entry for each conflicting address, and a device that is not known any more leaves nothing to show."""
from dataclasses import dataclass

LEVELS = {"info": "warn", "warning": "warn", "critical": "bad"}
WORST_FIRST = {"bad": 0, "warn": 1}
NOT_FOR_THE_PAGE = ("ids",)          # the ids of the devices are resolved here into names and addresses


@dataclass(frozen=True)
class Sources:
    by_id: dict
    by_mac: dict
    conflicts: dict
    gateway: dict | None


def _person(card: dict, ip: str | None = None) -> dict:
    return {"id": card["id"], "name": card.get("name") or None, "ip": ip or card.get("ip") or None}


def _addresses(finding, src: Sources) -> list[tuple[str, list[dict]]]:
    """One entry for each address that is answered by more than one MAC: a known device by name, an unknown one by its MAC."""
    out = []
    for ip, macs in sorted(src.conflicts.items()):
        people = [_person(src.by_mac[m.lower()], ip) if m.lower() in src.by_mac else {"name": None, "ip": ip, "mac": m.lower()} for m in macs]
        out.append((ip, people))
    return out


def _together(finding, src: Sources) -> list[tuple[str, list[dict]]]:
    return [(finding.subject, [_person(src.by_id[i]) for i in finding.evidence.get("ids", []) if i in src.by_id])]


def _one_device(finding, src: Sources) -> list[tuple[str, list[dict]]]:
    card = src.by_id.get(finding.subject)
    return [(finding.subject, [_person(card)] if card else [])]


def _gateway(finding, src: Sources) -> list[tuple[str, list[dict]]]:
    return [(finding.subject, [_person(src.gateway)] if src.gateway else [])]


WHO = {"addr": _addresses, "drop": _together, "boot": _one_device, "lat": _gateway}


def _entry(finding, tile: str, key: str, people: list[dict]) -> dict:
    return {"id": "%s:%s" % (finding.rule, key), "rule": finding.rule, "tile": tile, "lv": LEVELS.get(finding.severity, "warn"), "devs": people,
            "since": finding.first_seen, "last": finding.last_seen, "hits": finding.hits, "shadow": finding.shadow,
            "data": {k: v for k, v in finding.evidence.items() if k not in NOT_FOR_THE_PAGE}}


def _sources(devices: list[dict], conflicts: dict, gateway_ip: str | None) -> Sources:
    gateway = next((d for d in devices if gateway_ip and d.get("ip") == gateway_ip), None)
    return Sources({d["id"]: d for d in devices}, {str(d["mac"]).lower(): d for d in devices if d.get("mac")}, conflicts, gateway)


def build(findings: list, tiles: dict[str, str], devices: list[dict], conflicts: dict, gateway_ip: str | None) -> list[dict]:
    """The entries of the page: the worst first and then the newest. `tiles` maps a rule to the tile that holds it."""
    src = _sources(devices, conflicts, gateway_ip)
    out = []
    for finding in findings:
        tile = tiles.get(finding.rule)
        if finding.state != "active" or tile is None:
            continue
        out += [_entry(finding, tile, key, people) for key, people in WHO[tile](finding, src) if people]
    return sorted(out, key=lambda e: (WORST_FIRST[e["lv"]], -e["since"], e["id"]))
