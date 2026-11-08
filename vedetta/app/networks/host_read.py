"""The one reader of what the host says about its network: the default route and its gateway (/proc/net/route), the interfaces with their VLANs and addresses (/sys/class/net, /proc/net/vlan/config). Files of the kernel only, no external command (it also works with BusyBox).
Functions over a file or its text, with no state of their own: the callers keep their caches (iface keeps the interface for the whole run)."""
import ipaddress
from pathlib import Path

from .. import procfs
from ..applog import logger

SYS_NET = Path("/sys/class/net")
PROC = Path("/proc")


def parse_default_route(text: str) -> str | None:
    """Interface of the route with destination 0.0.0.0/0 and lowest metric."""
    best: tuple[int, str] | None = None
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8 or f[1] != "00000000" or f[7] != "00000000":
            continue
        try:
            metric = int(f[6])
        except ValueError:
            metric = 0
        if best is None or metric < best[0]:
            best = (metric, f[0])
    return best[1] if best else None


def read_gateway(route_path: str) -> str | None:
    """The gateway of the first default route of the file; None if there is none or the file cannot be read."""
    try:
        for cols in procfs.table(route_path):
            if _is_default_route(cols):
                return _gateway_text(cols[2])
    except ValueError:         # a bad number (or a byte that is not ASCII) ends the reading with no answer
        pass
    return None


def read_on_link(iface: str, route_path: str) -> list | None:
    """The networks reached on `iface` with no gateway (the routes of its own addresses), as the kernel has them now: they change the moment
    an address changes. None if the file cannot be read."""
    try:
        rows = [line.split() for line in procfs.lines(route_path)]
        if not rows:                 # not there or not readable (not Linux): nothing to say, not "no network"
            return None
        return [ipaddress.ip_network((_gateway_text(cols[1]), _gateway_text(cols[7])), strict=False) for cols in rows[1:] if _is_on_link_route(cols, iface)]
    except ValueError:
        return None


def _is_on_link_route(cols: list[str], iface: str) -> bool:
    """A line of /proc/net/route for `iface`, up (RTF_UP), with no gateway and not the default route."""
    return len(cols) >= 8 and cols[0] == iface and cols[2] == "00000000" and cols[1] != "00000000" and bool(int(cols[3], 16) & 1)


def _is_default_route(cols: list[str]) -> bool:
    """A line of /proc/net/route that is the default route and has the gateway flag (RTF_GATEWAY) set."""
    return len(cols) > 2 and cols[1] == "00000000" and bool(int(cols[3], 16) & 2)


def _gateway_text(hex_address: str) -> str:
    """Dotted address from the little-endian hexadecimal field of /proc/net/route."""
    raw = int(hex_address, 16).to_bytes(4, "little")
    return ".".join(str(b) for b in raw)


def parse_vlan_config(text: str) -> dict[str, dict]:
    """/proc/net/vlan/config: 'eth0.10 | 10 | eth0' -> {name: {id, parent}} (the header lines and anything odd are skipped)."""
    out = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[1].isdigit():
            out[parts[0]] = {"id": int(parts[1]), "parent": parts[2]}
    return out


def default_route_gateway(route_text: str) -> str | None:
    """The gateway of the default route (/proc/net/route keeps it as little-endian hex)."""
    name = parse_default_route(route_text)
    for line in route_text.splitlines()[1:]:
        f = line.split()
        if name and len(f) >= 8 and f[0] == name and f[1] == "00000000" and f[7] == "00000000":
            return ".".join(str(b) for b in reversed(bytes.fromhex(f[2])))
    return None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError as exc:
        logger.debug("network survey: %s not readable (%s)", path, exc)
        return ""


def _ipv4_addresses(name: str) -> list[dict]:
    """The first IPv4 address of an interface and its prefix (the kernel call BusyBox tools use); none on a system without it."""
    try:
        import fcntl
        import socket
        import struct
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            packed = struct.pack("256s", name.encode()[:15])
            address = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x8915, packed)[20:24])        # SIOCGIFADDR
            mask = socket.inet_ntoa(fcntl.ioctl(sock.fileno(), 0x891B, packed)[20:24])           # SIOCGIFNETMASK
    except (ImportError, OSError) as exc:                                    # no such module (not Linux) or an interface without an IPv4 address
        logger.debug("network survey: no IPv4 for %s (%s)", name, exc)
        return []
    return [{"address": address, "prefix": ipaddress.IPv4Network("0.0.0.0/" + mask).prefixlen}]


def _kind(path: Path, vlans: dict) -> str:
    if path.name == "lo":
        return "loopback"
    if (path / "bridge").is_dir():
        return "bridge"
    return "vlan" if path.name in vlans else "other"


def _interface(path: Path, vlans: dict, ipv4_of) -> dict:
    item = {"name": path.name, "kind": _kind(path, vlans), "state": _read(path / "operstate").strip() or None,
            "mac": _read(path / "address").strip() or None, "ipv4": ipv4_of(path.name)}
    if path.name in vlans:
        item["vlan"] = vlans[path.name]
    return item


def read_host(sys_net: Path = SYS_NET, proc: Path = PROC, ipv4_of=None) -> dict:
    """Interfaces, default interface and gateway of the host, from files only."""
    vlans = parse_vlan_config(_read(proc / "net" / "vlan" / "config"))
    route = _read(proc / "net" / "route")
    paths = sorted(sys_net.iterdir()) if sys_net.is_dir() else []
    return {"interfaces": [_interface(p, vlans, ipv4_of or _ipv4_addresses) for p in paths],
            "default_interface": parse_default_route(route), "gateway": default_route_gateway(route)}
