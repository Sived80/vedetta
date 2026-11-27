# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Network helpers: the local network of the host (get_local_network: subnet and own address, on the interface chosen in iface) and filter_local_ips, which keeps only the
addresses that belong to that network."""
import asyncio
import contextlib
import ipaddress
import re

from fastapi import HTTPException

from .applog import logger
from .iface import lan_iface

last_network: str | None = None     # the network of the last reading ("10.20.0.0/22"), None before the first one: what the page shows as the size of the LAN
last_own: str | None = None         # the own address of the last reading: the machine Vedetta runs on (never in the ARP view: nobody asks itself)


IP_COMMAND_TIMEOUT_S = 5


async def communicate_briefly(proc, timeout: float = IP_COMMAND_TIMEOUT_S) -> bytes:
    """The output of a local command that answers at once ("ip"); b"" when it does not within `timeout`, and the process is stopped."""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return out
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        return b""


async def get_local_network() -> tuple[str, str]:
    """Returns (CIDR subnet, the container's own IP), and keeps them in last_network and last_own."""
    global last_network, last_own
    proc = await asyncio.create_subprocess_exec(
        "ip", "-o", "-4", "addr", "show", lan_iface(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out = await communicate_briefly(proc)
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", out.decode())
    if not match:
        logger.error("Impossibile determinare la subnet locale, output 'ip addr': %r", out.decode())
        raise HTTPException(500, "Impossibile determinare la subnet locale")
    iface = ipaddress.ip_interface(match.group(1))
    network = iface.network if iface.network.prefixlen < HOST_PREFIX else await _host_address_network(iface.ip)
    last_network, last_own = str(network), str(iface.ip)
    return last_network, last_own


HOST_PREFIX = 31            # a /31 or /32 is the address of the host, not a network to watch
WIDEST_LINK_ROUTE = 16      # a link route wider than this is not taken as the LAN


async def _host_address_network(ip) -> ipaddress.IPv4Network:
    """The network around an own address given as /32 or /31 (a static address with a /32 mask, the gateway reached "on link"): the
    narrowest link route of the interface that holds the address, or the /24 around it. Without this the network was HA alone."""
    proc = await asyncio.create_subprocess_exec(
        "ip", "-4", "route", "show", "dev", lan_iface(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out = (await communicate_briefly(proc)).decode()
    held = [net for net in map(_link_route, out.splitlines()) if net and WIDEST_LINK_ROUTE <= net.prefixlen < HOST_PREFIX and ip in net]
    return max(held, key=lambda n: n.prefixlen) if held else ipaddress.ip_network(f"{ip}/24", strict=False)


def _link_route(line: str) -> ipaddress.IPv4Network | None:
    """The network of one line of `ip route` ("10.30.0.0/23 dev eth0 scope link"), None for the default route or a line without one."""
    words = line.split()
    if not words or "/" not in words[0]:
        return None
    try:
        return ipaddress.ip_network(words[0], strict=False)
    except ValueError:
        return None


async def filter_local_ips(ips: list[str]) -> list[str]:
    """Keeps only the IPs of the container's subnet. Without this check the
    scan endpoints accepted any IPv4: from a browser one could
    make the container launch nmap towards addresses outside the LAN."""
    subnet, _ = await get_local_network()
    network = ipaddress.ip_network(subnet)
    allowed, rejected = [], []
    for ip in ips:
        (allowed if ipaddress.ip_address(ip) in network else rejected).append(ip)
    if rejected:
        logger.warning("Scansione rifiutata, IP fuori dalla rete locale %s: %s", subnet, ", ".join(rejected))
    return allowed
