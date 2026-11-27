# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The MACs of the networks behind the router, from the router itself: its ARP table through SNMP (scan/snmp.py), when the person
wrote the router's address and a read-only community (settings.snmp_*). Off while either is empty: Vedetta never tries one.

Read once per sweep of the networks behind the router (routedwatch, every 15 minutes) and only for that: the table gives an address
its MAC (and so the maker of the device, K10), never its presence, because a router keeps an entry for minutes after the device
has gone. The last reading (when, how many rows, the error) is kept for the page; a failure is said once in the log.

With the table, the router's own address list (1.0.1): its address on each VLAN is the same machine as the one on the main network
(twins.py). A router that refuses that list still gives its table; the list is then empty. The list is kept in the data folder (1.0.2): after
a restart the twins by SNMP are there at once, not after the first sweep (up to 15 minutes later); it counts only for the router it was read from."""
import json
import time

from .. import paths
from ..applog import logger
from ..atomic import write_atomic
from ..storage import settings
from . import snmp

OWN_PATH = paths.data_path("router_own.json")
_last: dict = {"at": None, "rows": 0, "error": None, "ips": (), "own": frozenset()}
_kept: dict = {}             # the list of the last run, read once at the first question before a reading: {"router": address, "own": [...]}


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
    _last.update(at=time.time(), rows=len(found), error=None, ips=tuple(found), own=await _own(cfg))
    _keep(cfg["snmp_router"], _last["own"])
    return found


def _keep(router: str, own: frozenset) -> None:
    """The list just read, written for the next start (a failed write only costs the wait for the first reading)."""
    try:
        write_atomic(OWN_PATH, lambda f: json.dump({"router": router, "own": sorted(own)}, f), ".router-own-", durable=False)
    except OSError as exc:
        logger.debug("Indirizzi propri del router non salvati (%r)", exc)


def _kept_own(router: str) -> frozenset:
    """The list of the last run for this router; empty when there is none, it was read from another router or the file is damaged."""
    if not _kept:
        try:
            data = json.loads(OWN_PATH.read_text(encoding="utf-8"))
            _kept.update(router=str(data["router"]), own=frozenset(str(ip) for ip in data["own"]))
        except (OSError, ValueError, KeyError, TypeError):
            _kept.update(router=None, own=frozenset())
    return _kept["own"] if _kept["router"] == router else frozenset()


async def _own(cfg: dict) -> frozenset:
    """The router's own addresses; empty when it does not give them (said in the log at debug level only: the table is what counts)."""
    try:
        return frozenset(await snmp.own_addresses(cfg["snmp_router"], cfg["snmp_community"]))
    except Exception as exc:
        logger.debug("Indirizzi propri del router non letti via SNMP (%s)", type(exc).__name__)
        return frozenset()


def own_addresses() -> tuple[str | None, frozenset]:
    """(the address written as the router, the router's own addresses at its last good reading); (None, empty) without SNMP."""
    if not configured() or _last["error"]:
        return None, frozenset()
    router = settings.snmp_load()["snmp_router"]
    return router, _last["own"] if _last["at"] is not None else _kept_own(router)


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
