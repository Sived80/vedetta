"""How the check cycles go: a line in the log only when something is wrong (cycles chained by events, a slow cycle) and one summary an hour.

Counts and times only, never an address or a name: the numbers also go to the export (DeviceState.diagnostics)."""
import time
from collections import Counter, deque

from .applog import logger

CHAIN_WINDOW_S = 60.0     # more than CHAIN_WARN wake-ups in this window are written in the log, with their causes
CHAIN_WARN = 4
SLOW_CYCLE_S = 30.0       # a cycle that lasts longer is written in the log
SUMMARY_S = 3600.0        # one line in the log every hour: how the cycles went
WARN_EVERY_S = 600        # the same warning is not repeated more often than this


class CycleStats:
    def __init__(self) -> None:
        self._chain: deque = deque()
        self._chain_warned = -1e9
        self._slow_warned = -1e9
        self._stat: list[tuple[float, int, int]] = []       # (duration, addresses asked, hosts found) of the cycles since the last summary
        self._stat_since = time.monotonic()
        self._stat_chains = 0
        self.total_cycles = 0
        self.slowest = 0.0
        self.total_chains = 0
        self.last_summary: dict | None = None

    def note_start(self, cause: str, min_gap_s: float) -> None:
        now = time.monotonic()
        if cause and cause != "force":
            self._chain.append((now, cause))
        while self._chain and now - self._chain[0][0] > CHAIN_WINDOW_S:
            self._chain.popleft()
        if len(self._chain) >= CHAIN_WARN and now - self._chain_warned > WARN_EVERY_S:
            self._chain_warned = now
            causes = ", ".join("%s x%d" % (c, n) for c, n in Counter(c for _, c in self._chain).most_common())
            logger.warning("Controlli a catena: %d avviati da eventi in un minuto (%s); tra due controlli passano almeno %d s",
                           len(self._chain), causes, min_gap_s)
            self._stat_chains += 1
            self.total_chains += 1

    def note_end(self, started: float, asked: int, found: int, plan_info: dict | None) -> None:
        now = time.monotonic()
        dur = now - started
        self._stat.append((dur, asked, found))
        self.total_cycles += 1
        self.slowest = max(self.slowest, dur)
        if dur > SLOW_CYCLE_S and now - self._slow_warned > WARN_EVERY_S:
            self._slow_warned = now
            logger.warning("Controllo lento: %.0f s (%d indirizzi chiesti sulla rete)", dur, asked)
        if now - self._stat_since >= SUMMARY_S and self._stat:
            durs = sorted(s[0] for s in self._stat)
            n = len(self._stat)
            args = (n, durs[n // 2], durs[-1], sum(s[1] for s in self._stat) // n, sum(s[2] for s in self._stat) // n, self._stat_chains)
            if plan_info:
                logger.info("Ultima ora: %d controlli, durata mediana %.1f s, massima %.1f s, indirizzi chiesti in media %d, "
                            "host trovati in media %d, avviati a catena %d volte; rete grande %s: %d blocchi su %d gia' controllati",
                            *args, plan_info["network"], plan_info["done"], plan_info["total"])
            else:
                logger.info("Ultima ora: %d controlli, durata mediana %.1f s, massima %.1f s, indirizzi chiesti in media %d, "
                            "host trovati in media %d, avviati a catena %d volte", *args)
            self.last_summary = {"cycles": n, "median_s": round(durs[n // 2], 1), "max_s": round(durs[-1], 1), "chains": self._stat_chains,
                                 "addresses_asked": args[3], "hosts_found": args[4]}
            self._stat, self._stat_since, self._stat_chains = [], now, 0
