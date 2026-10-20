"""Upkeep of the identity of the cards: what to do when the same device shows up with another address or another card.

Three things, each done at the end of a check cycle: IP duplicates are reported once, an offline device whose known MAC answers at one other
address is followed there, and two cards of the same phone (new address and private MAC) are merged into the older one.

This is a mixin of DeviceState: it works on its cards, MACs and alerts. The single MAC layer planned for the new heart will replace it."""
import asyncio
import time

from .recognition import brands, naming
from .scan import scanner
from .storage import devices_config, newdevices
from .storage.overlap import SAME_MOMENT_S
from .storage.history import history

# Two cards of the same phone (it changed IP and private MAC): merged only if their names are the same and the two were
# never online together for longer than this (the 3 failed checks of tolerance already add a few minutes of overlap).
MERGE_MAX_OVERLAP_S = SAME_MOMENT_S
_GENERIC_PHONE_NAMES = {"iphone", "ipad", "android", "phone", "tablet", "galaxy", "pixel", "smartphone", "telefono", "cellulare"}


class IdentityUpkeep:
    def report_ip_conflicts(self) -> None:
        """Warns once for each IP answered by different MACs (scanner.arp_conflicts)."""
        for ip, macs in scanner.arp_conflicts.items():
            key = (ip, tuple(macs))
            if key in self._conflicts_reported:
                continue
            self._conflicts_reported.add(key)
            self.emit_alert(f"IP duplicato {ip}: risponde da {', '.join(macs)}", "alert.ip_conflict", ip=ip, macs=", ".join(macs))

    @staticmethod
    def _ips_by_mac(arp: dict[str, dict]) -> dict[str, list[str]]:
        """MAC (normalised) -> addresses that answer with it, in the order of the ARP view."""
        by_mac: dict[str, list[str]] = {}
        for ip, host in arp.items():
            mac = newdevices.normalize_mac(host.get("mac"))
            if mac:
                by_mac.setdefault(mac, []).append(ip)
        return by_mac

    def _moved_device(self, config: dict, arp: dict[str, dict], by_mac: dict[str, list[str]], used: set, holders: dict[str, dict]):
        """(card, new address) of an offline device whose known MAC answers at exactly one address nobody uses; None otherwise."""
        device = self.devices.get(config["id"])
        mac = newdevices.normalize_mac(self._last_mac.get(config["id"]))
        if not device or device.get("online") or not mac or config["ip"] in arp:
            return None
        # A MAC on multiple IPs belongs to a Wi-Fi repeater that "lends" its own
        # address to the clients connected to it (MAC translation): it does not identify a
        # device, so nothing is followed.
        if len(by_mac.get(mac, [])) != 1:
            return None
        candidates = [ip for ip in by_mac[mac] if ip not in used or self._holder_is_gone(ip, mac, holders)]
        return (device, candidates[0]) if len(candidates) == 1 else None

    def _holder_is_gone(self, ip: str, mac: str, holders: dict[str, dict]) -> bool:
        """The card that has this address in its settings is offline and its own last MAC is not the one that answers there: the address passed to another device."""
        holder = holders.get(ip)
        if holder is None or (self.devices.get(holder["id"]) or {}).get("online", True):
            return False
        return newdevices.normalize_mac(self._last_mac.get(holder["id"])) != mac

    async def _apply_ip_change(self, config: dict, device: dict, new_ip: str, used: set, holders: dict[str, dict]) -> None:
        """Writes the new address of the device, forgets the misses and tells it. An address held by a card that is gone is exchanged: that card takes the one left free."""
        holder = holders.get(new_ip)
        if holder is not None:
            old_ip = config["ip"]
            if not await asyncio.to_thread(devices_config.swap_ips, config["id"], holder["id"]):
                return
        else:
            old_ip = await asyncio.to_thread(devices_config.update_ip, config["id"], new_ip)
            if old_ip is None:
                return
        used.add(new_ip)
        holders[new_ip] = config
        if holder is None:
            used.discard(old_ip)
            holders.pop(old_ip, None)
        else:
            holders[old_ip] = holder
        self._misses[config["id"]] = 0
        label = device.get("name") or old_ip
        self.emit_alert(f"{label}: IP cambiato {old_ip} -> {new_ip}", "alert.ip_changed",
                        label=label, old=old_ip, new=new_ip)
        self.trigger(reason="ip_changed")

    async def follow_ip_changes(self, arp: dict[str, dict]) -> None:
        """An offline device whose (already known) MAC now answers at exactly ONE other
        IP not assigned to other devices has changed address (DHCP): it is followed
        instead of being given up as off. No action if the candidates are ambiguous."""
        if not arp:
            return
        by_mac = self._ips_by_mac(arp)
        configs = devices_config.load_devices()
        used = {c["ip"] for c in configs}
        holders = {c["ip"]: c for c in configs}
        for config in configs:
            moved = self._moved_device(config, arp, by_mac, used, holders)
            if moved is not None:
                await self._apply_ip_change(config, moved[0], moved[1], used, holders)

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

    async def _older_and_newer(self, cards: list[dict], now: float) -> tuple[dict, dict, float]:
        """The two cards by age (the first seen is the older) and how long they were online together in the last week."""
        first_seen = await asyncio.to_thread(history.first_presence, [c["id"] for c in cards])
        older, newer = sorted(cards, key=lambda c: first_seen.get(c["id"], now))
        overlap = await asyncio.to_thread(history.online_overlap, older["id"], newer["id"], now - 7 * 86400, now)
        return older, newer, overlap

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
        older, newer, overlap = await self._older_and_newer(cards, now)
        if overlap > MERGE_MAX_OVERLAP_S:
            outcome["online_together"] += 1
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
        self._misses[keep_id] = 0
        self.remove(drop_id)
        self._announce_merge(keep, drop_id, old_ip, new_ip, address)
        self.trigger(reason="phones_merged")
