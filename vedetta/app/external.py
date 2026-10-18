"""The functions that reach the internet, and the add-on options that switch them off (config.yaml: internet_*; run.sh turns them into VEDETTA_INTERNET_*).

  public IP       a DNS query to OpenDNS (scan/internet.py)             every 6 hours
  path            a traceroute to a public address, 1.1.1.1 by default  every 6 hours
  MAC database    the download of the IEEE registries (recognition/oui_update.py)

Everything is on unless the option says otherwise. Outside the add-on (no variable at all) the first two stay on, as they always were, and the MAC database
follows its own setting file (off by default). Nothing here reads a file or the network: it only reads the environment, so a test can set it."""
import logging
import os
import re

logger = logging.getLogger("dashboard")

DEFAULT_PATH_TARGET = "1.1.1.1"
# A host name or an address (IPv4, IPv6): letters, digits, dots, colons and hyphens, never a hyphen first (the target becomes an argument of nmap).
_TARGET = re.compile(r"^(?!-)[A-Za-z0-9.:-]{1,253}$")


def _flag(name: str) -> bool | None:
    """True / False when the variable says so, None when it is missing or empty."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return None
    return raw not in ("false", "0", "no", "off")


def public_ip_enabled() -> bool:
    flag = _flag("VEDETTA_INTERNET_PUBLIC_IP")
    return True if flag is None else flag


def path_enabled() -> bool:
    flag = _flag("VEDETTA_INTERNET_PATH")
    return True if flag is None else flag


def mac_database_setting() -> bool | None:
    """The add-on option for the MAC database, or None when there is none (then the setting file of the app decides)."""
    return _flag("VEDETTA_INTERNET_MAC_DB")


def path_target() -> str:
    raw = os.environ.get("VEDETTA_INTERNET_PATH_TARGET", "").strip()
    if not raw:
        return DEFAULT_PATH_TARGET
    if _TARGET.match(raw):
        return raw
    logger.warning("Riferimento del traceroute non valido (%r): uso %s", raw[:40], DEFAULT_PATH_TARGET)
    return DEFAULT_PATH_TARGET


def any_internet_check() -> bool:
    return public_ip_enabled() or path_enabled()


def status() -> dict:
    """What the page needs to say about the first two (the third is added by the route, it needs the date of the last update)."""
    return {"public_ip": {"on": public_ip_enabled()}, "path": {"on": path_enabled(), "target": path_target()}}
