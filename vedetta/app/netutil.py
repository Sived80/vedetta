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
    """Returns (CIDR subnet, the container's own IP), and keeps the subnet in last_network."""
    global last_network
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
    last_network = str(iface.network)
    return last_network, str(iface.ip)


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
