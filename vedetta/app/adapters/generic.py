import asyncio
import re

MAC_RE = re.compile(r"([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})")


async def _tcp_check(ip: str, port: int, timeout: float = 1.0) -> bool:
    # Dimezzato da 2.0s: su una LAN un host raggiungibile risponde in pochi
    # millisecondi, quindi questo timeout scatta solo per host davvero offline
    # - e siccome la pagina aspetta tutte le probe prima di mostrare qualcosa,
    # ogni dispositivo spento aggiungeva fino a 2s alla comparsa delle card.
    # L'ARP scan condiviso (vedi probe.py) resta comunque la rete di sicurezza
    # per i falsi negativi di un host lento ma presente.
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
    # Il fallback via ping e' stato tolto: un dispositivo irraggiungibile via
    # TCP ci metteva fino a 4s (2s TCP + 2s ping in sequenza) solo per
    # risultare comunque offline, bloccando la pagina a ogni refresh. La
    # scansione ARP condivisa (vedi probe.py/main.py) copre gia' meglio lo
    # stesso caso - un dispositivo senza porte aperte ma presente in rete -
    # in un colpo solo per tutti i dispositivi, non ripetuta uno per uno.
    online = await _tcp_check(ip, port)
    mac = await _get_mac(ip)
    return {"online": online, "mac": mac}
