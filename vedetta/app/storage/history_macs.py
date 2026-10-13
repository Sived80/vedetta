"""MacMemoryMixin: methods of History that belong together (moved out of history.py by tools/split_class.py)."""


class MacMemoryMixin:
    def last_mac(self, device_id: str) -> str | None:
        """Latest known MAC of a device (used to wake it up when it is
        off and the probe no longer sees its MAC)."""
        with self._lock:
            row = self._db.execute(
                "SELECT mac FROM presence_events WHERE device_id = ? AND mac IS NOT NULL ORDER BY id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        return row["mac"] if row else None

    # ---- shadow data per MAC (analysis only) ----
    def mac_memory_set(self, mac: str, device_id: str, ip: str | None, fields: dict, ts: float) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mac_memory (mac, first_seen, last_seen, device_id, ip, name, brand, grp, mobile_score, dhcp_name, dhcp_class)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(mac) DO UPDATE SET last_seen = excluded.last_seen, device_id = excluded.device_id, ip = excluded.ip,
                       name = excluded.name, brand = excluded.brand, grp = excluded.grp, mobile_score = excluded.mobile_score,
                       dhcp_name = excluded.dhcp_name, dhcp_class = excluded.dhcp_class, hits = hits + 1""",
                (mac, ts, ts, device_id, ip, fields.get("name"), fields.get("brand"), fields.get("grp"), fields.get("mobile_score"),
                 fields.get("dhcp_name"), fields.get("dhcp_class")))
            self._db.commit()

    def mac_memory_for(self, device_id: str) -> list[dict]:
        """The memory per MAC of the MACs seen behind a card, the oldest first."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM mac_memory WHERE device_id = ? ORDER BY first_seen", (device_id,)).fetchall()
        return [dict(r) for r in rows]

    def mac_known(self, mac: str) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM mac_memory WHERE mac = ?", (mac,)).fetchone() is not None

    def mac_takeover_add(self, ts: float, device_id: str, ip: str | None, old_mac: str, new_mac: str, carried: dict,
                         old_dhcp: dict, new_dhcp: dict, new_known: bool) -> None:
        with self._lock:
            self._db.execute(
                """INSERT INTO mac_takeover (ts, device_id, ip, old_mac, new_mac, carried_name, carried_brand, carried_grp,
                       old_dhcp_class, new_dhcp_class, old_dhcp_name, new_dhcp_name, new_known) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ts, device_id, ip, old_mac, new_mac, carried.get("name"), carried.get("brand"), carried.get("grp"),
                 old_dhcp.get("vendor_class"), new_dhcp.get("vendor_class"), old_dhcp.get("hostname"), new_dhcp.get("hostname"),
                 int(new_known)))
            self._db.commit()
