"""The detectors: one small pure function for each family of problem. A detector reads the signals and the parameters of its row and returns the evidence it finds (nothing if the signal is quiet or unreadable). Evidence holds counts, never addresses or names."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Evidence:
    subject: str                       # whom it is about: a device id, "lan", "gateway", "internet" or "self"
    data: dict = field(default_factory=dict)


def conflict(signals: dict, params: dict) -> list[Evidence]:
    """An IP answered by more than one MAC (signals["conflicts"]: ip -> list of MACs)."""
    conflicts = signals.get("conflicts")
    if not isinstance(conflicts, dict) or not conflicts:
        return []
    return [Evidence("lan", {"ips": len(conflicts), "macs": sum(len(macs) for macs in conflicts.values())})]


FAMILIES = {"conflict": conflict}
