"""The one judgement of "are these two MACs the same device?". Pure: only the two profiles and what is passed in.

Two parts of the app ask this question about the MACs behind one card: the notice of a second device behind it (ha/identity_shift.py) and the automatic name that the card keeps
(scan/probe_names.py). They share this function, so they share the rules:
  - vetoes turn the answer into "unknown": a MAC behind two or more cards at once (a repeater lending its own, a NAT), a MAC that belongs to a network role, and (for a policy that asks
    for it) a private (random) MAC, whose rotation makes "another MAC" mean nothing by itself;
  - evidence that it is ONE device (the same DHCP name, the same Bonjour name, the same Home Assistant device) wins over any difference;
  - otherwise the families of evidence that it is TWO devices are counted, each family once (a fact is never counted twice): the answer is "different" when the policy's minimum is reached.
A policy only says how much evidence a consumer wants before it acts and which families it reads. It is not a second set of rules. A profile is a dict with every key of `profile()`; a fact that is
not known is None, and an unknown fact never counts."""
from dataclasses import dataclass

NETWORK_ROLES = {"gateway", "dhcp", "dns", "router", "ap", "repeater"}


@dataclass(frozen=True)
class Policy:
    name: str
    families: tuple          # the families of evidence read, in the order in which the reasons are listed
    min_families: int        # how many of them must agree for "different"
    private_vetoes: bool     # a private (random) MAC forbids judging


# A notice to the user is rocky on purpose: two independent families, and a private MAC (a phone) is left alone.
NOTIFY = Policy("notify", ("dhcp_family", "group", "dhcp_name", "mdns_name", "ha_model"), 2, True)
# The name of a card is silent and recoverable (the device announces it again): the DHCP fingerprint of the two MACs (RFC 2132, options 55 and 60), which does not change when a phone
# rotates its MAC, is enough. The DHCP family of NOTIFY is read from the same request, so the two are never counted together.
NAME = Policy("name", ("dhcp_fingerprint",), 1, False)


def profile(mac: str, **known) -> dict:
    """A profile of a MAC with what is known about it; everything else is None (not known), so that the judgement never meets a missing key."""
    return {"mac": mac, "private": False, "family": None, "grp": None, "dhcp_name": None, "mdns_name": None, "ha": None, "fingerprint": None, **known}


def fingerprint(entry: dict | None) -> tuple[str, str] | None:
    """(parameter request list in its order, vendor class without case or spaces) of a DHCP entry; None when the MAC sent neither."""
    entry = entry or {}
    prl, vendor_class = entry.get("prl") or "", (entry.get("vendor_class") or "").strip().lower()
    return (prl, vendor_class) if prl or vendor_class else None


def is_network(role_names) -> bool:
    """The roles of an address include one of a gateway, a DHCP or DNS server, a router, an access point or a repeater."""
    return bool(NETWORK_ROLES & set(role_names or ()))


def judge(a: dict, b: dict, shared: set[str], role_a: bool = False, role_b: bool = False, policy: Policy = NOTIFY) -> dict:
    """{"verdict": "different" | "same" | "unknown", "reasons": [...], "vetoes": [...]}."""
    vetoes = _vetoes(a, b, shared, role_a, role_b, policy)
    if vetoes:
        return {"verdict": "unknown", "reasons": [], "vetoes": vetoes}
    same = same_reasons(a, b)
    if same:
        return {"verdict": "same", "reasons": same, "vetoes": []}
    diff = different_reasons(a, b, policy)
    return {"verdict": "different" if len(diff) >= policy.min_families else "unknown", "reasons": diff, "vetoes": []}


def _vetoes(a: dict, b: dict, shared: set[str], role_a: bool, role_b: bool, policy: Policy) -> list[str]:
    """What forbids judging at all."""
    vetoes = []
    if policy.private_vetoes and (a["private"] or b["private"]):
        vetoes.append("private")
    if a["mac"] in shared or b["mac"] in shared:
        vetoes.append("shared")
    if role_a or role_b:
        vetoes.append("role")
    return vetoes


def same_reasons(a: dict, b: dict) -> list[str]:
    """The evidence that it is the same device: the same DHCP name, the same Bonjour name, the same Home Assistant device."""
    same = []
    if a["dhcp_name"] and a["dhcp_name"] == b["dhcp_name"]:
        same.append("dhcp_name")
    if a["mdns_name"] and a["mdns_name"] == b["mdns_name"]:
        same.append("mdns_name")
    if a["ha"] and a["ha"] == b["ha"] and any(a["ha"]):
        same.append("ha_model")
    return same


def different_reasons(a: dict, b: dict, policy: Policy = NOTIFY) -> list[str]:
    """The independent families of evidence, among those of the policy, that the two are different devices, in a fixed order."""
    return [name for name in policy.families if _CHECKS[name](a, b)]


def _field_differs(a: dict, b: dict, key: str) -> bool:
    """Both profiles have a value for `key` and the values are not equal."""
    return bool(a[key] and b[key] and a[key] != b[key])


def _group_differs(a: dict, b: dict) -> bool:
    """Both profiles have a real recognised group (not missing, not "generic") and the groups are not equal."""
    return a["grp"] not in (None, "generic") and b["grp"] not in (None, "generic") and a["grp"] != b["grp"]


def _ha_model_differs(a: dict, b: dict) -> bool:
    """Both have a Home Assistant (brand, model) with something in it, and the two pairs are not equal."""
    if not (a["ha"] and b["ha"]):
        return False
    return (a["ha"][0], a["ha"][1]) != (b["ha"][0], b["ha"][1]) and any(a["ha"][:2]) and any(b["ha"][:2])


_CHECKS = {
    "dhcp_family": lambda a, b: _field_differs(a, b, "family"),
    "group": _group_differs,
    "dhcp_name": lambda a, b: _field_differs(a, b, "dhcp_name"),
    "mdns_name": lambda a, b: _field_differs(a, b, "mdns_name"),
    "ha_model": _ha_model_differs,
    "dhcp_fingerprint": lambda a, b: _field_differs(a, b, "fingerprint"),
}
