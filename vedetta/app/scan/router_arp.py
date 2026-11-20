"""The MACs of the networks behind the router, from the router itself: its ARP table through SNMP (scan/snmp.py), when the person
wrote the router's address and a read-only community (settings.snmp_*). Off while either is empty: Vedetta never tries one.

Read once per sweep of the networks behind the router (routedwatch, every 15 minutes) and only for that: the table gives an address
its MAC (and so the maker of the device, K10), never its presence, because a router keeps an entry for minutes after the device
has gone. The last reading (when, how many rows, the error) is kept for the page; a failure is said once in the log."""
import time

from ..applog import logger
from ..storage import settings
from . import snmp

_last: dict = {"at": None, "rows": 0, "error": None, "ips": ()}


def configured() -> bool:
    cfg = settings.snmp_load()
    return bool(cfg["snmp_router"] and cfg["snmp_community"])


async def table() -> dict[str, str]:
    """{IPv4: MAC} of the router now; {} when not configured or on error (the error is kept for the page)."""
    cfg = settings.snmp_load()
    if not (cfg["snmp_router"] and cfg["snmp_community"]):
        return {}
    try:
        found = await snmp.arp_table(cfg["snmp_router"], cfg["snmp_community"])
    except Exception as exc:
        _fail(f"{type(exc).__name__}: {exc}"[:200] if str(exc) else type(exc).__name__)
        return {}
    if _last["error"]:
        logger.info("Tabella ARP del router di nuovo leggibile (%d indirizzi)", len(found))
    _last.update(at=time.time(), rows=len(found), error=None, ips=tuple(found))
    return found


def last_ips() -> tuple:
    """The addresses the router gave a MAC for at its last good reading (the networks panel: «MAC: on, from the router»)."""
    return _last["ips"] if configured() and not _last["error"] else ()


def _fail(reason: str) -> None:
    if _last["error"] != reason:
        logger.warning("Tabella ARP del router non letta via SNMP (%s)", reason)
    _last.update(at=time.time(), error=reason)


def status() -> dict:
    """For the page: configured or not, and the last reading."""
    return {**settings.snmp_public(), "last_at": _last["at"], "last_rows": _last["rows"], "last_error": _last["error"]}


async def test() -> dict:
    """«Try»: one reading now, what it found or why not."""
    if not configured():
        return {"ok": False, "error": "not_configured"}
    found = await table()
    return {"ok": _last["error"] is None, "rows": len(found), "error": _last["error"]}
