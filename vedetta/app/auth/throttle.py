# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The wait after wrong attempts (login and first setup).

OWASP (Authentication Cheat Sheet) asks to slow down guessing without locking the owner out for good: after FREE wrong attempts each
new one must wait, 1 second doubling up to MAX_WAIT_S (15 minutes); a right password clears the count. The count is kept both per
address and for the whole app: one address cannot try faster by itself, many addresses together cannot either (there is one account).
In memory only: a restart of the container clears it, which needs access to the host anyway."""
import threading
import time

FREE = 5
FIRST_WAIT_S = 1.0
MAX_WAIT_S = 15 * 60
MAX_ADDRESSES = 1000
GLOBAL = "*"


class Throttle:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}       # address -> (wrong attempts in a row, time of the last one)

    def _wait_of(self, key: str, now: float) -> float:
        count, last = self._fails.get(key, (0, 0.0))
        if count < FREE:
            return 0.0
        wait = min(MAX_WAIT_S, FIRST_WAIT_S * 2 ** (count - FREE))
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
