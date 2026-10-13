"""The view of the network that ARP gives: who answers at which address and with which MAC.

On a normal network (up to a /24) the whole network is asked every FULL_SWEEP_S and the configured devices in the checks between; on a large
network a plan of blocks is asked, a few at a time, and what each block told is remembered (see scan/arpplan.py). The result is cached for
a few seconds so that the probes of a cycle share one answer. Knows nothing about cards, events or alerts: the new-device watch is told
about the blocks asked for the first time through a callback."""
import asyncio
import ipaddress
import os
import time
from collections.abc import Callable

from . import netutil
from .applog import logger
from .scan import arpplan, scanner
from .storage import devices_config
from .storage.history import history

ARP_CYCLE_TIMEOUT_S = 60.0   # arp-scan of the periodic check that does not finish is closed
# A normal network (up to a /24): a sweep of every address (about 625 requests in a burst) at every check is more than presence needs, and a
# weak Wi-Fi, a repeater or a mesh feels it. The whole network is asked once in FULL_SWEEP_S (to find the new devices); the checks between ask
# only the devices that are configured. Every ARP request is paced SWEEP_INTERVAL_MS apart instead of in a burst.
FULL_SWEEP_S = 300.0
SWEEP_INTERVAL_MS = 20
ARP_MEMORY_S = 24 * 3600     # on a large network, what a block told is kept this long (see scan/arpplan.py)
NET_TTL_S = 300.0


class ArpView:
    def __init__(self, on_fresh_blocks: Callable[[list], None]) -> None:
        self.on_fresh_blocks = on_fresh_blocks              # blocks of a large network asked for the first time
        self.cache: tuple[float, dict[str, dict]] | None = None
        self.lock = asyncio.Lock()
        self.mem: dict[str, tuple[float, dict]] = {}        # ip -> (when, host) of what the ARP told so far (large network: its blocks; normal: the last sweep)
        self.last_full: float | None = None                 # when the whole network was last asked (None: at the next check)
        self.net: tuple[float, str, str] | None = None      # (when, network, own address), re-read every NET_TTL_S
        self.plan_info: dict | None = None                  # last plan of a large network: {"network", "total", "done"}
        self.asked = 0
        self.found = 0
        self.first_blocks_logged = False

    async def network(self) -> tuple[str, str] | None:
        """(network, own address) of the interface, read again every NET_TTL_S; None if it cannot be read."""
        now = time.monotonic()
        if self.net is None or now - self.net[0] > NET_TTL_S:
            try:
                cidr, own = await netutil.get_local_network()
                self.net = (now, cidr, own)
            except Exception:
                if self.net is None:
                    return None
        return self.net[1], self.net[2]

    def whole_size(self) -> int:
        """Addresses of the whole network when it is asked whole (a /24: 256)."""
        try:
            return ipaddress.ip_network(self.net[1], strict=False).num_addresses if self.net else 0
        except ValueError:
            return 0

    @staticmethod
    def _known_ips() -> list[str]:
        """Addresses of the configured devices first, then of the known ones (thread)."""
        ips = [c["ip"] for c in devices_config.load_devices() if c.get("ip")]
        return ips + [r["ip"] for r in history.known_all().values() if r.get("ip")]

    async def _arp_plan(self) -> dict | None:
        """None: the whole network is asked (up to a /24, as always). Otherwise the plan of a large network (scan/arpplan.py)."""
        net = await self.network()
        if net is None:
            return None
        try:
            known = await asyncio.to_thread(self._known_ips)
            blocks = await asyncio.to_thread(history.scan_blocks)
            return arpplan.plan(net[0], net[1], known, blocks, force=bool(os.environ.get("VEDETTA_ARP_BLOCKS")))
        except Exception:
            logger.exception("Piano ARP fallito: si chiede solo la rete attorno a questo computer")
            return arpplan.own_block_only(net[1])

    @staticmethod
    def _asked_by(plan: dict):
        """(blocks of the plan, test that says whether an address was asked: a single target or inside a block)."""
        blocks = [ipaddress.ip_network(b) for b in plan["blocks"]]
        singles = {t for t in plan["targets"] if t not in plan["blocks"]}

        def asked(ip: str) -> bool:
            return ip in singles or any(ipaddress.ip_address(ip) in b for b in blocks)
        return blocks, asked

    def _forget_asked_or_old(self, asked: Callable[[str], bool], now: float) -> None:
        """What the blocks asked now replace is forgotten, and so is what is older than ARP_MEMORY_S."""
        mem = self.mem
        for ip in [i for i, (ts, _) in mem.items() if asked(i) or now - ts > ARP_MEMORY_S]:
            del mem[ip]

    async def _add_neighbours(self, plan: dict, asked: Callable[[str], bool], now: float) -> None:
        """The neighbours the system has just seen, when they were not asked and are not remembered."""
        mem = self.mem
        for h in await scanner.neighbors(plan["network"]):
            if h["ip"] not in mem and not asked(h["ip"]):
                mem[h["ip"]] = (now, h)

    async def _mark_blocks(self, blocks: list, now: float) -> None:
        """How many hosts each block holds is saved (a failure is only logged)."""
        found = {str(b): sum(1 for i in self.mem if ipaddress.ip_address(i) in b) for b in blocks}
        try:
            await asyncio.to_thread(history.scan_blocks_mark, found, now)
        except Exception:
            logger.debug("Blocchi ARP non salvati", exc_info=True)

    async def _remember(self, hosts: list[dict], plan: dict) -> dict[str, dict]:
        """Large network: what the blocks asked now replace what was remembered of them; the rest is kept (up to ARP_MEMORY_S), so the
        view of the network fills in cycle after cycle. The neighbours the system has just seen are added at no cost."""
        now = time.time()
        blocks, asked = self._asked_by(plan)
        self._forget_asked_or_old(asked, now)
        for h in hosts:
            self.mem[h["ip"]] = (now, h)
        await self._add_neighbours(plan, asked, now)
        await self._mark_blocks(blocks, now)
        self.on_fresh_blocks(plan["fresh"])
        self.plan_info = {"network": plan["network"], "total": plan["total"], "done": plan["done"] + len(plan["fresh"])}
        return {ip: h for ip, (_, h) in self.mem.items()}

    @staticmethod
    def _configured_ips() -> list[str]:
        """Addresses of the configured devices (thread)."""
        return [c["ip"] for c in devices_config.load_devices() if c.get("ip")]

    async def _arp_small(self) -> tuple[dict[str, dict], int]:
        """A normal network: the whole network at most every FULL_SWEEP_S, the configured devices in the checks between. Returns the view
        of the ARP (what the last sweep found, updated by the devices asked since) and how many addresses were asked now."""
        now = time.monotonic()
        known = await asyncio.to_thread(self._configured_ips)
        if not known or self.last_full is None or now - self.last_full >= FULL_SWEEP_S:
            hosts = await scanner.arp_scan(interval_ms=SWEEP_INTERVAL_MS)
            self.mem = {h["ip"]: (time.time(), h) for h in hosts}
            self.last_full = now
            return {ip: h for ip, (_, h) in self.mem.items()}, self.whole_size()
        hosts = await scanner.arp_scan(known, timeout=ARP_CYCLE_TIMEOUT_S, interval_ms=SWEEP_INTERVAL_MS)
        for ip in known:
            self.mem.pop(ip, None)                # whoever was asked and does not answer is gone from the view
        for h in hosts:
            self.mem[h["ip"]] = (time.time(), h)
        return {ip: h for ip, (_, h) in self.mem.items()}, len(known)

    async def _read_small(self) -> tuple[dict[str, dict], int]:
        """A network of normal size: the view and how many addresses were asked."""
        if self.plan_info is not None:
            logger.info("Rete di dimensione normale: tutta la rete ogni %d minuti, nei giri in mezzo solo i dispositivi configurati", FULL_SWEEP_S // 60)
        self.plan_info = None
        return await self._arp_small()

    async def _read_blocks(self, plan: dict) -> tuple[dict[str, dict], list[dict]]:
        """A large network: the view (with what is remembered) and the hosts that answered now."""
        if self.plan_info is None:
            logger.info("Rete grande (%s, %d blocchi da 256 indirizzi): a ogni giro si chiede la rete attorno a questo computer, "
                        "i dispositivi noti e un blocco in piu', a turno", plan["network"], plan["total"])
        hosts = await scanner.arp_scan(plan["targets"], timeout=ARP_CYCLE_TIMEOUT_S)
        return await self._remember(hosts, plan), hosts

    def _log_first_blocks(self, hosts: list[dict]) -> None:
        if not self.first_blocks_logged:
            self.first_blocks_logged = True
            logger.info("Primo giro a blocchi: %d indirizzi chiesti, %d host trovati", self.asked, len(hosts))

    async def _read_arp(self) -> None:
        """Reads the ARP once (the whole network or the plan of blocks) and caches the view."""
        plan = await self._arp_plan()
        if plan is None:
            result, self.asked = await self._read_small()
            self.found = len(result)
        else:
            result, hosts = await self._read_blocks(plan)
            self.asked = sum(ipaddress.ip_network(x).num_addresses for x in plan["targets"])
            self.found = len(result)
            self._log_first_blocks(hosts)
        self.cache = (time.monotonic(), result)

    def _cache_empty_if_none(self) -> None:
        if self.cache is None:
            self.cache = (time.monotonic(), {})

    async def _refresh_cache(self) -> None:
        try:
            await self._read_arp()
        except asyncio.TimeoutError:
            logger.warning("La ricerca ARP non e' finita in tempo e si e' fermata: si usa l'ultimo risultato")
            self._cache_empty_if_none()
        except Exception:
            logger.exception("Scansione ARP fallita")
            self._cache_empty_if_none()

    async def by_ip(self, max_age: float) -> dict[str, dict]:
        async with self.lock:
            now = time.monotonic()
            if self.cache is None or now - self.cache[0] > max_age:
                await self._refresh_cache()
            return self.cache[1]
