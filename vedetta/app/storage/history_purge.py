# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""PurgeMixin: every row of the history that belongs to one written network, counted or deleted («delete this network», networks/purge.py).

A row belongs to the network when it is about one of its cards (device_id in the ids given), when its address is in the network (inside(ip), the
predicate given by the caller), or, for card_mac and routed_seen, when it names the network. mac_class keeps the verdict on a MAC that was seen elsewhere too.
The same rules count (the preview the page shows) and delete (one transaction), so the numbers the page shows are the rows that go."""
import json

_IDS = "device_id IN (SELECT value FROM json_each(:ids))"
# In this order: mac_class looks at ip_mac before its rows go.
RULES = (
    ("mac_class", "mac IN (SELECT mac FROM ip_mac WHERE inside(ip)) AND mac NOT IN (SELECT mac FROM ip_mac WHERE NOT inside(ip))"),
    ("presence_events", _IDS + " OR inside(ip)"),
    ("scans", _IDS),
    ("latency", _IDS),
    ("identity_change", _IDS),
    ("mac_memory", _IDS + " OR inside(ip)"),
    ("mac_takeover", _IDS + " OR inside(ip)"),
    ("card_mac", _IDS + " OR network = :net OR inside(ip)"),
    ("health_finding", "subject IN (SELECT value FROM json_each(:ids))"),
    ("known_macs", "inside(ip)"),
    ("ip_mac", "inside(ip)"),
    ("ip_mac_session", "inside(ip)"),
    ("ip_flip", "inside(ip)"),
    ("ip_conflict", "inside(ip)"),
    ("scan_blocks", "inside(block)"),
    ("routed_seen", "network = :net OR inside(ip)"),
)
# The MACs seen in the network: what the page calls «MAC addresses seen» (and what tells an ignored MAC of this network).
_SEEN = (f"SELECT mac FROM presence_events WHERE {_IDS} OR inside(ip) UNION SELECT mac FROM mac_memory WHERE {_IDS} OR inside(ip)"  # noqa: S608
         " UNION SELECT mac FROM ip_mac WHERE inside(ip) UNION SELECT mac FROM known_macs WHERE inside(ip)"
         " UNION SELECT mac FROM routed_seen WHERE network = :net OR inside(ip)")
SEEN_MACS = "SELECT DISTINCT mac FROM (" + _SEEN + ") WHERE mac IS NOT NULL AND mac != ''"  # noqa: S608 (constants only)


class PurgeMixin:
    def purge_network(self, inside, device_ids: list, network_id: str, apply: bool = False, meta_keys: tuple = ()) -> dict:
        """{"rows": rows of the network, "macs": the MACs seen in it}; with apply=True the rows are deleted (the count is of the rows deleted).
        inside(address) says whether an address (or the first address of a block "a.b.c.d/nn") is in the network. meta_keys: service values
        deleted in the same transaction (the main network starts over: newdevices.BASELINE_KEY)."""
        params = {"ids": json.dumps(sorted(set(device_ids))), "net": network_id}
        with self._lock:
            self._db.create_function("inside", 1, lambda value: int(bool(value) and inside(str(value).split("/")[0])), deterministic=True)
            macs = sorted(r[0] for r in self._db.execute(SEEN_MACS, params).fetchall())
            try:
                rows = sum(self._purge_rows(table, where, params, apply) for table, where in RULES)
                self._db.executemany("DELETE FROM meta WHERE key = ?", [(k,) for k in meta_keys if apply])
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return {"rows": rows, "macs": macs}

    def _purge_rows(self, table: str, where: str, params: dict, apply: bool) -> int:
        if apply:
            return self._db.execute("DELETE FROM " + table + " WHERE " + where, params).rowcount  # noqa: S608 (table and condition are the constants above)
        return self._db.execute("SELECT COUNT(*) FROM " + table + " WHERE " + where, params).fetchone()[0]  # noqa: S608
