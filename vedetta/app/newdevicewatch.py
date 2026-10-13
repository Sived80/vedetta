"""Watch for MACs never seen on the network: compares what ARP and DHCP show with the known ones and warns once for each new one.

Holds the state of that watch (the current set of "new" MACs, the blocks of a large network asked for the first time, the own address).
Sending the events and the alerts is left to the caller through two callbacks, so this module knows nothing about DeviceState."""
import asyncio
from collections.abc import Callable

from . import netutil
from .applog import logger
from .scan import dhcp
from .storage import blocklist, devices_config, newdevices, settings


class NewDeviceWatch:
    def __init__(self, devices: Callable[[], dict], emit: Callable[[dict], None], emit_alert: Callable[..., None]) -> None:
        self._devices = devices            # the cards in memory: their MACs are configured ones
        self._emit = emit
        self._emit_alert = emit_alert
        self.macs: frozenset[str] = frozenset()
        self.baseline_blocks: tuple[str, ...] = ()   # blocks of a large network asked for the first time: the starting point, not new devices
        self.own_ip: str | None = None
        self._lock = asyncio.Lock()

    def set(self, devices: list[dict]) -> None:
        """Stores the list of 'new' devices and emits the event only if the set of MACs has changed."""
        macs = frozenset(d["mac"] for d in devices)
        changed = macs != self.macs
        self.macs = macs
        if changed:
            self._emit(newdevices.event(devices))

    def _configured_macs(self) -> "set[str]":
        """MACs of the cards in memory: they are configured devices, not new ones."""
        return {m for m in (newdevices.normalize_mac(d.get("mac")) for d in self._devices().values()) if m}

    async def _skip_ips(self) -> "set[str]":
        """Addresses left out of the comparison: our own, looked up the first time (a failure of the lookup is not an error)."""
        skip_ips = {self.own_ip} if self.own_ip else set()
        if self.own_ip is None:
            try:
                _, self.own_ip = await netutil.get_local_network()
                skip_ips = {self.own_ip}
            except Exception:
                pass
        return skip_ips

    async def _evaluate(self, arp: dict[str, dict]) -> tuple[list[dict], list[dict]]:
        """(devices to alert, full list of the new ones) after comparing the seen MACs with the known ones."""
        configs = devices_config.load_devices()
        configured_macs = self._configured_macs()
        skip_ips = await self._skip_ips()
        observed = newdevices.observed_macs(arp, dhcp.seen, skip_ips)
        observed = {m: o for m, o in observed.items()
                    if not blocklist.matches(mac=m, ip=o["ip"], name=o["hostname"])}
        baseline, self.baseline_blocks = self.baseline_blocks, ()
        return await asyncio.to_thread(
            newdevices.evaluate, observed, {c["ip"] for c in configs}, configured_macs, newdevices.own_macs(),
            baseline_blocks=baseline,
        )

    def _warn_new(self, fresh: list[dict]) -> None:
        """One alert (or, with the alerts off, one log line) for each new device."""
        alerts_on = settings.alerts_enabled()
        for dev in fresh:
            label = newdevices.readable_label(dev)
            ip = dev["ip"] or "-"
            message = f"Nuovo dispositivo in rete: {label} ({ip}) MAC {dev['mac']}"
            if alerts_on:
                self._emit_alert(message, "alert.new_device", label=label, ip=ip)
            else:
                logger.info(message)

    async def check(self, arp: dict[str, dict]) -> None:
        """Compares the seen MACs (ARP already available, no new scan) with the known ones; warns about never-seen ones."""
        async with self._lock:
            try:
                fresh, current = await self._evaluate(arp)
            except Exception:
                logger.exception("Controllo nuovi dispositivi fallito")
                return
            self._warn_new(fresh)
            self.set(current)
