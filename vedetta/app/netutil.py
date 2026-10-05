import asyncio
import ipaddress
import re

from fastapi import HTTPException

from .applog import logger
from .iface import lan_iface


async def get_local_network() -> tuple[str, str]:
    """Returns (CIDR subnet, the container's own IP)."""
    proc = await asyncio.create_subprocess_exec(
        "ip", "-o", "-4", "addr", "show", lan_iface(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", out.decode())
    if not match:
        logger.error("Impossibile determinare la subnet locale, output 'ip addr': %r", out.decode())
        raise HTTPException(500, "Impossibile determinare la subnet locale")
    iface = ipaddress.ip_interface(match.group(1))
    return str(iface.network), str(iface.ip)


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
