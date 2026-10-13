"""scan_arp: moved out of scanner.py (see tools/split_module.py)."""
import asyncio
from .scan_common import is_valid_ipv4
from ..iface import lan_iface
from .arpplan import parse_neighbors
import contextlib


# IPs to which different MACs responded in the last arp-scan (address conflict).
arp_conflicts: dict[str, list[str]] = {}


ARP_TIMEOUT_S = 120.0   # arp-scan that does not finish is closed: the cycle goes on with the last result


async def arp_scan(targets: list[str] | None = None, timeout: float = ARP_TIMEOUT_S, interval_ms: int | None = None) -> list[dict]:
    """Host discovery via ARP: layer 2 only, no ICMP/TCP fallback like nmap
    -sn. On a typical /24 it runs in 1-2 seconds instead of 3-5.
    targets None: the whole network of the interface (--localnet). Otherwise only those (addresses and CIDR blocks, see
    scan/arpplan.py), given on the standard input. A scan that does not end within `timeout` seconds is killed and TimeoutError raised.

    No logging in here: it is also called on every page refresh (behind
    a 15s cache, see get_cached_arp_by_ip in main.py), not only when
    the user launches a search - logging it anyway would have filled the buffer
    with routine events invisible to the user, burying in a few minutes
    the useful ones (real scans, errors). Whoever calls it for an
    explicit action (quick_scan) logs at that level.

    interval_ms: minimum pause between two packets (arp-scan --interval, milliseconds). Without it arp-scan sends about 500 packets a
    second, a burst that a weak Wi-Fi, a repeater or a mesh feels; with 20 ms the same sweep is spread over a few seconds."""
    args = ["arp-scan", f"--interface={lan_iface()}", "-x"] + (["--file=-"] if targets else ["--localnet"])
    if interval_ms:
        args.append(f"--interval={int(interval_ms)}")
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if targets else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate("\n".join(targets).encode() if targets else None), timeout)
    except BaseException:       # timeout, or the cycle was cancelled: never leave the process running
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        raise
    hosts = parse_arp_scan(out.decode(errors="replace"))
    if not hosts and proc.returncode not in (0, None):
        raise RuntimeError("arp-scan ended with code %s" % proc.returncode)   # not an empty network: the check keeps the last result
    return hosts


async def neighbors(net: str | None = None) -> list[dict]:
    """The neighbours the system has just seen answer (`ip neigh`): they cost no packet. [] if it cannot be read."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "-4", "-o", "neigh", "show", "dev", lan_iface(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
    except Exception:
        return []
    return parse_neighbors(out.decode(errors="replace"), net)


def own_host(own_ip: str | None, arp_hosts: list[dict]) -> dict | None:
    """The computer the app runs on: ARP never lists it (nobody asks itself
    "who has this IP?"), so it is added by hand with the MAC of its network interface."""
    if not own_ip or any(h["ip"] == own_ip for h in arp_hosts):
        return None
    try:
        with open(f"/sys/class/net/{lan_iface()}/address", encoding="ascii") as fh:
            mac = fh.read().strip().upper()
    except OSError:
        return None
    if len(mac) != 17 or mac == "00:00:00:00:00:00":
        return None
    return {"ip": own_ip, "mac": mac, "vendor": None}


def parse_arp_scan(text: str) -> list[dict]:
    """arp-scan lines -> hosts. An address that replies more than once ("DUP" lines,
    typical of repeaters and routers with proxy ARP) appears only once: the
    first reply is kept."""
    hosts, seen = [], set()
    macs_by_ip: dict[str, set[str]] = {}
    for ip, mac, vendor in _arp_rows(text):
        macs_by_ip.setdefault(ip, set()).add(mac)
        if ip not in seen:
            seen.add(ip)
            hosts.append({"ip": ip, "mac": mac, "vendor": vendor})
    arp_conflicts.clear()
    arp_conflicts.update(_real_conflicts(macs_by_ip))
    return hosts


def _arp_rows(text: str):
    """(ip, MAC in capitals, vendor or None) of each valid line of arp-scan, in order; the same address may appear more than once."""
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and is_valid_ipv4(parts[0]):
            vendor = parts[2].strip() if len(parts) >= 3 and not parts[2].startswith("(Unknown") else None
            yield parts[0], parts[1].upper(), vendor


def _real_conflicts(macs_by_ip: dict[str, set[str]]) -> dict[str, list[str]]:
    """Several MACs on the same IP, and none of those MACs also answers for other IPs (that would be an ARP proxy or a repeater,
    not a duplicate address)."""
    mac_ips: dict[str, set[str]] = {}
    for ip, macs in macs_by_ip.items():
        for mac in macs:
            mac_ips.setdefault(mac, set()).add(ip)
    return {ip: sorted(macs) for ip, macs in macs_by_ip.items() if len(macs) > 1 and all(len(mac_ips[m]) == 1 for m in macs)}
