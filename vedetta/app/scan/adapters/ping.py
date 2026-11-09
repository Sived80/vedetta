"""Ping adapter (K1): asks a device only whether it answers an ICMP echo. For the cards of a confirmed network behind the router with touch
"presence": no TCP connection, no port, no name request; the MAC is never known there (ARP does not cross the router: K10)."""
from .. import latency


async def probe(ip: str, port: int = 80) -> dict:
    return {"online": await latency.icmp_ms(ip, latency.TIMEOUT) is not None, "mac": None}
