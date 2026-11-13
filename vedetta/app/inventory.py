"""The single inventory (1.0 step P7): who is on the network, remembered, instead of the snapshot of the last ARP read.

Built from what the MAC layer already keeps (ip_mac: address, MAC, source, first and last sight), for every (network, MAC) seen in the last
KEEP_S: the last address, the sources that saw it, first and last sight, and a state (decision 1A of 13/11):
  - candidate: one source only and never an ARP answer (a DHCP request alone, an mDNS announcement alone): it never raises an alert;
  - confirmed: an ARP answer, or two different sources whose last sights are at most CONFIRM_WINDOW_S apart;
  - asleep: confirmed, and nothing heard for more than ASLEEP_S;
  - out of the inventory after KEEP_S without news.
Nothing is stored: the inventory is computed again from the data (a few hundred rows). Pure."""
from collections import Counter

CONFIRM_WINDOW_S = 600          # two sources within 10 minutes confirm a device (decision 1A)
ASLEEP_S = 900                  # a confirmed device silent for 15 minutes is asleep
KEEP_S = 7 * 86400              # out of the inventory after 7 days without news
ANSWER = "arp"                  # an ARP answer of the MAC itself (arp_dup, the second MAC of a double answer, is a source but not an answer)


def _mac(raw) -> str | None:
    mac = str(raw or "").strip().upper().replace("-", ":")
    return mac if len(mac) == 17 else None


def build(rows, now: float, network_of=lambda ip: "main") -> dict[tuple[str, str], dict]:
    """(network, MAC) -> {ip, sources, first_seen, last_seen, state}. rows: dicts with ip, mac, source, first_seen, last_seen (ip_mac);
    network_of(ip): the network of an address, None to leave it out (registry.direct_networks)."""
    seen: dict[tuple[str, str], dict[str, dict]] = {}
    for r in rows:
        mac, net = _mac(r.get("mac")), network_of(r.get("ip"))
        if not mac or not net or now - r["last_seen"] > KEEP_S:
            continue
        per_source = seen.setdefault((net, mac), {})
        _merge(per_source, r)
    return {key: _entry(per_source, now) for key, per_source in seen.items()}


def _merge(per_source: dict[str, dict], r: dict) -> None:
    """The row into the sight of its source: the first first sight, the last last sight and its address."""
    got = per_source.get(r["source"])
    if got is None:
        per_source[r["source"]] = {"first": r["first_seen"], "last": r["last_seen"], "ip": r["ip"]}
        return
    got["first"] = min(got["first"], r["first_seen"])
    if r["last_seen"] >= got["last"]:
        got["last"], got["ip"] = r["last_seen"], r["ip"]


def _entry(per_source: dict[str, dict], now: float) -> dict:
    last_source = max(per_source, key=lambda s: (per_source[s]["last"], s == ANSWER))
    last = per_source[last_source]["last"]
    confirmed = ANSWER in per_source or _two_close(per_source)
    state = ("asleep" if now - last > ASLEEP_S else "confirmed") if confirmed else "candidate"
    return {"ip": per_source[last_source]["ip"], "sources": set(per_source), "first_seen": min(s["first"] for s in per_source.values()),
            "last_seen": last, "state": state}


def _two_close(per_source: dict[str, dict]) -> bool:
    """Two different sources whose last sights are at most CONFIRM_WINDOW_S apart."""
    lasts = sorted(s["last"] for s in per_source.values())
    return any(b - a <= CONFIRM_WINDOW_S for a, b in zip(lasts, lasts[1:]))


def counts(inv: dict[tuple[str, str], dict]) -> dict:
    """What the export carries: MACs, by state, by set of sources (numbers only, never a MAC or an address)."""
    return {"macs": len(inv), "states": dict(Counter(e["state"] for e in inv.values())),
            "sources": dict(Counter("+".join(sorted(e["sources"])) for e in inv.values()))}
