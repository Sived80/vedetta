import asyncio
import ipaddress
import re

from fastapi import HTTPException

from .applog import logger
from .iface import lan_iface


async def get_local_network() -> tuple[str, str]:
    """Ritorna (subnet CIDR, IP proprio del container)."""
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
    """Tiene solo gli IP della subnet del container. Senza questo controllo gli
    endpoint di scansione accettavano qualunque IPv4: da un browser si poteva
    far lanciare nmap dal container verso indirizzi esterni alla LAN."""
    subnet, _ = await get_local_network()
    network = ipaddress.ip_network(subnet)
    allowed, rejected = [], []
    for ip in ips:
        (allowed if ipaddress.ip_address(ip) in network else rejected).append(ip)
    if rejected:
        logger.warning("Scansione rifiutata, IP fuori dalla rete locale %s: %s", subnet, ", ".join(rejected))
    return allowed
