"""Which addresses the periodic check asks over ARP.

On a normal home network (a /24 or smaller: 254 addresses) the whole network is asked every time, as it always was. On a wider network
(a /16 has 65,534 addresses) asking everything every minute would flood the network and the machine, so the check asks only:
  - the /24 around this machine (the home network, in every cycle),
  - the addresses of the devices already known, wherever they are (in every cycle),
  - ONE more /24 of the network, the one that has waited longest: the database fills in block by block, and starts again from the
    oldest block when it has gone round. What was learned is kept (storage/history.py, table scan_blocks), so a restart goes on from
    where it was.
No more than MAX_TARGETS addresses per cycle, whatever the network. A network wider than a /16 is read as the /16 around this machine.
Pure functions, no network access: see tests/check_arpplan.py."""
import ipaddress

FULL_PREFIX = 24     # a /24 or smaller is asked whole
WIDEST_PREFIX = 16   # nothing wider than a /16 is ever walked through
MAX_KNOWN = 512      # addresses of known devices asked besides the two blocks
MAX_TARGETS = 1024   # 2 blocks of 256 + MAX_KNOWN


def _network(cidr: str) -> ipaddress.IPv4Network | None:
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return None
    return net if net.version == 4 else None


def _in(ip: str, net: ipaddress.IPv4Network) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.version == 4 and addr in net


def block_of(ip: str) -> str | None:
    """The /24 that holds an address ("192.168.1.0/24"), None if it is not an IPv4 address."""
    try:
        return str(ipaddress.ip_network(f"{ip}/24", strict=False)) if ipaddress.ip_address(ip).version == 4 else None
    except ValueError:
        return None


def plan(cidr: str, own_ip: str | None, known_ips: list[str], block_ts: dict[str, float], force: bool = False) -> dict | None:
    """None: ask the whole network (small network, or unreadable). Otherwise {"network", "targets", "blocks", "total", "done"}:
    targets = what arp-scan is given; blocks = the /24 blocks asked whole in this cycle (own first); total = blocks in the network;
    done = how many of them have been asked at least once (before this cycle); fresh = the blocks asked for the very first time now
    (their devices are a starting point, not "new devices": see storage/newdevices.py). block_ts = {block: when it was last asked}."""
    net = _network(cidr)
    own = block_of(own_ip) if own_ip else None
    if net is not None and net.prefixlen >= FULL_PREFIX and force and own:
        net = ipaddress.ip_network(own)     # `force` (only for trying it out on a small network, VEDETTA_ARP_BLOCKS): the /24 is treated as a block
    elif net is None or net.prefixlen >= FULL_PREFIX:
        return None
    if net.prefixlen < WIDEST_PREFIX:
        if own is None:          # wider than a /16 and we do not know where we are: only the devices already known
            singles = [str(a) for a in dict.fromkeys(ip for ip in known_ips if _in(ip, net))][:MAX_KNOWN]
            return {"network": str(net), "targets": singles, "blocks": [], "total": 0, "done": 0, "fresh": []}
        net = ipaddress.ip_network(f"{own_ip}/{WIDEST_PREFIX}", strict=False)
    blocks = [str(b) for b in net.subnets(new_prefix=FULL_PREFIX)]
    others = [b for b in blocks if b != own]
    # the block that has waited longest (never asked first, in address order)
    chosen = min(others, key=lambda b: (block_ts.get(b, -1.0), blocks.index(b))) if others else None
    asked = [b for b in (own, chosen) if b]
    nets = [ipaddress.ip_network(b) for b in asked]
    singles = []
    for ip in dict.fromkeys(known_ips):      # in the given order (the configured devices first), no repeats
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.version != 4 or addr not in net or any(addr in n for n in nets):
            continue
        singles.append(str(addr))
        if len(singles) >= MAX_KNOWN:
            break
    return {"network": str(net), "targets": asked + singles, "blocks": asked, "total": len(blocks),
            "done": sum(1 for b in blocks if b in block_ts), "fresh": [b for b in asked if b != own and b not in block_ts]}


def own_block_only(own_ip: str | None) -> dict | None:
    """The safe fallback when planning itself fails: only the /24 around this machine."""
    own = block_of(own_ip) if own_ip else None
    return {"network": own, "targets": [own], "blocks": [own], "total": 1, "done": 1, "fresh": []} if own else None


def parse_neighbors(text: str, net: str | None = None) -> list[dict]:
    """`ip -4 -o neigh show dev X` -> [{ip, mac, vendor}] of the entries the system has just seen answer (REACHABLE): they cost no packet.
    STALE and the like prove nothing, so they are left out."""
    area = _network(net) if net else None
    hosts = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4 or "lladdr" not in parts or parts[-1] != "REACHABLE":
            continue
        try:
            ip = str(ipaddress.ip_address(parts[0]))
            mac = parts[parts.index("lladdr") + 1].upper()
        except (ValueError, IndexError):
            continue
        if len(mac) != 17 or (area is not None and ipaddress.ip_address(ip) not in area):
            continue
        hosts.append({"ip": ip, "mac": mac, "vendor": None})
    return hosts
