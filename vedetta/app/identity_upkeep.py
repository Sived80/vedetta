"""Upkeep of the identity of the cards: what to do when the same device shows up with another address or another card.

Three things, each done at the end of a check cycle: IP duplicates are reported once, a linked card whose MAC answered at another address follows
it there (1.0 step P5, with the card -> MAC link; the old rule that followed the last MAC seen is gone), and two cards of the same phone (new
address and private MAC) are merged into the older one (the kept card's link is released: it had the other MAC).

This is a mixin of DeviceState: it works on its cards, MACs and alerts."""
import asyncio
import logging
import time

from . import linkview, macpresence, macverdict, netutil
from .networks import registry
from .recognition import brands, naming
from .storage import devices_config
from .storage.overlap import SAME_MOMENT_S
from .storage.history import history

# Two cards of the same phone (it changed IP and private MAC): merged only if their names are the same and the two were
# never online together for longer than this (the 3 failed checks of tolerance already add a few minutes of overlap).
MERGE_MAX_OVERLAP_S = SAME_MOMENT_S
_OVERLAP_LOG_STEP_S = 600          # a pair that stays unmerged is logged again only when its overlap grows by this much
logger = logging.getLogger("dashboard")
_overlap_logged: dict[tuple[str, str], float] = {}     # (older id, newer id) -> overlap at the last line written
_GENERIC_PHONE_NAMES = {"iphone", "ipad", "android", "phone", "tablet", "galaxy", "pixel", "smartphone", "telefono", "cellulare"}


class IdentityUpkeep:
    def report_ip_conflicts(self) -> None:
        """Warns once for each IP contested by different MACs, and each set of them, while the app runs: the conflicts going on of the single verdict
        (macverdict, judged in time by macclassify; since 1.0 step P3, before it was the last ARP scan)."""
        for ip, macs in macverdict.conflicts(time.time()).items():
            key = (ip, tuple(macs))
            if key in self._conflicts_reported:
                continue
            self._conflicts_reported.add(key)
            self.emit_alert(f"IP duplicato {ip}: risponde da {', '.join(macs)}", "alert.ip_conflict", ip=ip, macs=", ".join(macs))

    async def follow_links(self, moves: dict[str, str]) -> None:
        """The linked cards found at another address in this cycle (state_cycle: their MAC alone answered there) follow their MAC (1.0 step P5):
        the plan of macpresence.follow, written at once (devices_config.set_ips). A move goes to an address on the line of the card's own direct
        network that may hold a card (not paused, K9a); a card that held the address takes the one left free. Each card that moves is told
        (alert.ip_changed) and its misses forgotten; the cycle is woken once. Nothing when the file changed meanwhile (tried at the next cycle)."""
        cards, plan = self._follow_plan(moves)
        if not plan or not await asyncio.to_thread(devices_config.set_ips, {cid: (cards[cid], ip) for cid, ip in plan.items()}):
            return
        for cid, ip in plan.items():
            self._misses[cid] = 0
            label = (self.devices.get(cid) or {}).get("name") or cards[cid]
            self.emit_alert(f"{label}: IP cambiato {cards[cid]} -> {ip}", "alert.ip_changed", label=label, old=cards[cid], new=ip)
        self.trigger(reason="ip_changed")

    @staticmethod
    def _follow_plan(moves: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
        """(card id -> address now, card id -> new address): the moves that may go ahead, with the cards they push to the address left free."""
        if not moves:
            return {}, {}
        cards = {c["id"]: c["ip"] for c in devices_config.load_devices() if c.get("ip")}
        nets = registry.direct_networks([*cards.values(), *moves.values()], netutil.last_network)

        def allowed(cid: str, ip: str) -> bool:
            return nets.get(ip) is not None and nets.get(ip) == nets.get(cards[cid]) and registry.may_add(ip)
        return cards, macpresence.follow(cards, moves, allowed)

    @staticmethod
    def _alnum_lower(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    @staticmethod
    def _is_bare_brand(name: str, key: str) -> bool:
        """The name is only the name of a brand."""
        known = brands.known_brand(name)
        return bool(known) and IdentityUpkeep._alnum_lower(known) == key

    @staticmethod
    def _duplicate_key(device: dict) -> str | None:
        """Name that identifies a phone well enough to say that two cards are the same one; None if it does not
        (a bare "iPhone", the IP, a placeholder, a brand)."""
        name = (device.get("name") or "").strip()
        key = IdentityUpkeep._alnum_lower(name)
        if len(key) < 4 or name == device.get("ip") or naming.is_placeholder(name) or key in _GENERIC_PHONE_NAMES:
            return None
        return None if IdentityUpkeep._is_bare_brand(name, key) else key

    def _phone_groups(self) -> dict[str, list[dict]]:
        """Mobile cards grouped by their distinctive name."""
        groups: dict[str, list[dict]] = {}
        for device in self.devices.values():
            key = self._duplicate_key(device) if device.get("is_mobile") else None
            if key:
                groups.setdefault(key, []).append(device)
        return groups

    async def _older_and_newer(self, cards: list[dict], now: float) -> tuple[dict, dict, float, dict[str, float]]:
        """The two cards by age (the first seen is the older), how long they were online together in the last week, and when each was first seen."""
        first_seen = await asyncio.to_thread(history.first_presence, [c["id"] for c in cards])
        older, newer = sorted(cards, key=lambda c: first_seen.get(c["id"], now))
        overlap = await asyncio.to_thread(history.online_overlap, older["id"], newer["id"], now - 7 * 86400, now)
        return older, newer, overlap, first_seen

    @staticmethod
    def _log_online_together(older: dict, newer: dict, overlap: float, first_seen: dict[str, float], now: float) -> None:
        """Says in the log why two cards of one name were not merged: how long they were online together, when each card was first seen (hours ago,
        older first) and whether each is online now, which is where a false overlap can come from. Once per pair, again only when the time grows by
        more than _OVERLAP_LOG_STEP_S (the check runs at every cycle). Cards by id, never by name."""
        key = (older["id"], newer["id"])
        if overlap - _overlap_logged.get(key, -_OVERLAP_LOG_STEP_S) < _OVERLAP_LOG_STEP_S:
            return
        _overlap_logged[key] = overlap
        ages = [(now - first_seen[c["id"]]) / 3600 if c["id"] in first_seen else float("nan") for c in (older, newer)]
        online = [("yes" if c.get("online") else "no") for c in (older, newer)]
        logger.info("Phone cards %s and %s not merged: online together %d s in the last week (limit %d s); first seen %.1f h and %.1f h ago; online now: %s, %s",
                    older["id"], newer["id"], round(overlap), MERGE_MAX_OVERLAP_S, ages[0], ages[1], online[0], online[1])

    async def _merge_group(self, cards: list[dict], now: float, outcome: dict) -> None:
        """One group of cards with the same name: merged if it is clear, otherwise the reason is counted."""
        if len(cards) < 2:
            return
        if len(cards) != 2:
            outcome["three_or_more"] += 1
            return
        if not any(c.get("online") for c in cards):
            outcome["both_offline"] += 1
            return
        older, newer, overlap, first_seen = await self._older_and_newer(cards, now)
        if overlap > MERGE_MAX_OVERLAP_S:
            outcome["online_together"] += 1
            self._log_online_together(older, newer, overlap, first_seen, now)
            return
        await self._merge_cards(keep=older, drop=newer, now=now)
        outcome["merged"] += 1

    async def merge_duplicate_phones(self) -> None:
        """A phone that changes IP and private MAC leaves an offline card and gets a new one. When exactly two mobile
        cards have the same distinctive name, at least one is online now and they were never online together for
        long, they are the same device: the older card (it keeps the choices made by hand and the history) takes the
        address of the one that answers, the other disappears and its history goes with it. Nothing is done if it is
        not clear (three cards, same name online together)."""
        groups = self._phone_groups()
        now = time.time()
        outcome = {"merged": 0, "three_or_more": 0, "both_offline": 0, "online_together": 0}
        for cards in groups.values():
            await self._merge_group(cards, now, outcome)
        # counts only (for the export): they explain a merge that did not happen without any name
        self.merged_total += outcome["merged"]
        self.merge_report = {**outcome, "merged_total": self.merged_total}

    @staticmethod
    def _scan_is_newer(newer_scan: dict, keep_config: dict) -> bool:
        return newer_scan.get("scanned_at", 0) > (keep_config.get("scan_info") or {}).get("scanned_at", 0)

    async def _keep_address(self, keep_id: str, address: str, old_ip: str) -> bool:
        """The kept card takes the address that answers; False if the configuration refuses it."""
        if address == old_ip:
            return True
        return await asyncio.to_thread(devices_config.update_ip, keep_id, address) is not None

    def _move_last_mac(self, drop_id: str, keep_id: str) -> None:
        if self._last_mac.get(drop_id):
            self._last_mac[keep_id] = self._last_mac.pop(drop_id)

    def _announce_merge(self, keep: dict, drop_id: str, old_ip: str, new_ip: str, address: str) -> None:
        keep_id = keep["id"]
        label = keep.get("name") or old_ip
        self.emit_alert(f"{label}: schede unite (stesso telefono) {drop_id} -> {keep_id}", "alert.duplicate_merged",
                        label=label, old=old_ip if address != old_ip else new_ip, new=address)

    async def _merge_cards(self, keep: dict, drop: dict, now: float) -> None:
        keep_id, drop_id = keep["id"], drop["id"]
        old_ip, new_ip = keep["ip"], drop["ip"]
        # the address that answers is the one kept: the card that is online decides it
        address = new_ip if drop.get("online") or not keep.get("online") else old_ip
        configs = {c["id"]: c for c in devices_config.load_devices()}
        if keep_id not in configs or drop_id not in configs:
            return
        newer_scan = (configs[drop_id].get("scan_info") or {})
        ok = await asyncio.to_thread(devices_config.remove_device, drop_id)
        if not ok:
            return
        if not await self._keep_address(keep_id, address, old_ip):
            return
        if self._scan_is_newer(newer_scan, configs[keep_id]):
            await asyncio.to_thread(devices_config.update_scan_info, keep_id, newer_scan)
        await asyncio.to_thread(history.reassign_device, drop_id, keep_id)
        self._move_last_mac(drop_id, keep_id)
        linkview.release(keep_id)            # the kept card's link was the other private MAC: released, deleted by the one writer
        self._misses[keep_id] = 0
        self.remove(drop_id)
        self._announce_merge(keep, drop_id, old_ip, new_ip, address)
        self.trigger(reason="phones_merged")
