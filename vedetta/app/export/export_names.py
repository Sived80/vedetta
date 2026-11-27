# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Names the export for the developer must learn before masking, beyond the board and the registries (review of 19/11):
- what a deep search read from the device itself (scan_info / scans.result_json): its UPnP, NetBIOS, ONVIF names, the name its local interface
  gives (ESPHome, Shelly, Sonos...), the nmap host name, and the name in its web page title or certificate when they look like a name;
- the names the history database keeps for cards removed and for guests (mac_memory, known_macs, mac_takeover).
A name learnt here is masked wherever it is written; one never learnt would stay readable and the final check would not see it.
An e-mail address is not learnt as a name: it has its own placeholder (email-N@masked.invalid) and its own check."""
import json
import sqlite3

from ..recognition import naming
from .anonymize_patterns import _EMAIL

# the fields of a deep search that hold a name the device (or its owner) gave it
_NAME_FIELDS = ("upnp_name", "netbios_name", "onvif_name", "api_name", "hostname")
# the history columns that hold a name, one fixed query each (no SQL is ever put together from pieces)
_DB_NAMES = ("SELECT DISTINCT name, dhcp_name FROM mac_memory",
             "SELECT DISTINCT hostname FROM known_macs",
             "SELECT DISTINCT carried_name, old_dhcp_name, new_dhcp_name FROM mac_takeover")


def scan_names(info) -> list:
    """The names in one deep search result; the title and the certificate only when naming would take them as a name."""
    if not isinstance(info, dict):
        return []
    out = [info.get(k) for k in _NAME_FIELDS]
    out += [naming.title_name(info.get("http_title")), naming.cn_host(info.get("tls_subject"))]
    return [n for n in out if _usable(n)]


def history_names(history) -> list:
    """Every name in the searches kept in the history and in the name columns of the MAC tables. A table that cannot be read gives nothing."""
    with history._lock:
        searched = [n for (raw,) in _rows(history, "SELECT DISTINCT result_json FROM scans") for n in scan_names(_json(raw))]
        kept = [v for sql in _DB_NAMES for row in _rows(history, sql) for v in row if _usable(v)]
    return searched + kept


def _usable(v) -> bool:
    return isinstance(v, str) and bool(v.strip()) and not _EMAIL.search(v)


def _rows(history, sql: str) -> list:
    try:
        return history._db.execute(sql).fetchall()
    except sqlite3.Error:                   # an old database without that table or column: nothing to learn from it
        return []


def _json(raw):
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
