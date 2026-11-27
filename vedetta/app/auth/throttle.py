# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The wait after wrong attempts (login and first setup: one Throttle each, they count apart).

OWASP (Authentication Cheat Sheet) asks to slow down guessing without locking the owner out. Two counts:
- per address: after FREE wrong attempts each new one waits 1 second, doubling up to MAX_WAIT_S (15 minutes);
- for the whole app (many addresses together, there is one account): after GLOBAL_FREE wrong attempts it waits 1 second, doubling up to
  GLOBAL_MAX_WAIT_S only (30 seconds). A short global wait, so a stranger failing now and then cannot keep the owner out from another
  address (security review of 27/11); the long wait stays on the address that guesses.
A right password clears the count of its address and the global one. The caller counts an attempt as failed BEFORE checking it
(routes/auth_routes.py), so attempts sent at the same moment cannot all pass the check of the wait first. In memory only: a restart of
the container clears it, which needs access to the host anyway."""
import threading
import time

FREE = 5
FIRST_WAIT_S = 1.0
MAX_WAIT_S = 15 * 60
GLOBAL_FREE = 20
GLOBAL_MAX_WAIT_S = 30
MAX_ADDRESSES = 1000
GLOBAL = "*"


class Throttle:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}       # address (or GLOBAL) -> (wrong attempts in a row, time of the last one)

    def _wait_of(self, key: str, now: float) -> float:
        count, last = self._fails.get(key, (0, 0.0))
        free, cap = (GLOBAL_FREE, GLOBAL_MAX_WAIT_S) if key == GLOBAL else (FREE, MAX_WAIT_S)
        if count < free:
            return 0.0
        wait = min(cap, FIRST_WAIT_S * 2 ** min(count - free, 30))
        return max(0.0, last + wait - now)

    def wait(self, address: str) -> float:
        """Seconds this address must still wait before the next attempt (0 = it may try now)."""
        now = self._clock()
        with self._lock:
            return max(self._wait_of(address, now), self._wait_of(GLOBAL, now))

    def failed(self, address: str) -> None:
        now = self._clock()
        with self._lock:
            for key in (address, GLOBAL):
                count, _ = self._fails.get(key, (0, 0.0))
                self._fails[key] = (count + 1, now)
            self._forget_oldest()

    def _forget_oldest(self) -> None:
        """Many addresses: the oldest are forgotten, the global count stays (called with the lock held)."""
        extra = len(self._fails) - MAX_ADDRESSES
        oldest = [key for key, _ in sorted(self._fails.items(), key=lambda kv: kv[1][1]) if key != GLOBAL][:max(0, extra)]
        for key in oldest:
            self._fails.pop(key, None)

    def succeeded(self, address: str) -> None:
        with self._lock:
            self._fails.pop(address, None)
            self._fails.pop(GLOBAL, None)
