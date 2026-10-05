import asyncio
import re

MAC_RE = re.compile(r"([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})")


async def _tcp_check(ip: str, port: int, timeout: float = 1.0) -> bool:
    # Halved from 2.0s: on a LAN a reachable host answers in a few
    # milliseconds, so this timeout only fires for truly offline hosts
    # - and since the page waits for all the probes before showing anything,
    # every powered-off device added up to 2s to the appearance of the cards.
    # The shared ARP scan (see probe.py) remains the safety net anyway
    # for false negatives of a slow but present host.
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def _get_mac(ip: str) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show", ip,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await proc.communicate()
    except Exception:
        return None
    match = MAC_RE.search(out.decode())
    return match.group(1).upper() if match else None


async def probe(ip: str, port: int = 80) -> dict:
    # The ping fallback was removed: a device unreachable via
    # TCP took up to 4s (2s TCP + 2s ping in sequence) just to
    # end up offline anyway, blocking the page on every refresh. The
    # shared ARP scan (see probe.py/main.py) already covers better the
    # same case - a device with no open ports but present on the network -
    # in one go for all devices, not repeated one by one.
    online = await _tcp_check(ip, port)
    mac = await _get_mac(ip)
    return {"online": online, "mac": mac}
