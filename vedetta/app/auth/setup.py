# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The first start: there is no password yet and the page asks to choose one, but only to whoever can read the log of the container.

Whoever reaches the page first must not be the one who chooses the password (a stranger on the same network). At start, when no password
is set, a one-time code is made (12 characters from an alphabet without look-alike letters) and written in the log, once; the setup page
asks it with the password. The code is valid VALID_S (one hour) from the start and only until a password is set: after that the setup
page answers 404. A container restarted later prints a new code. The code is kept in memory only, never on disk."""
import hmac
import secrets
import time

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LENGTH = 12
VALID_S = 3600


class SetupCode:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._code: str | None = None
        self._made = 0.0

    def make(self) -> str:
        self._code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        self._made = self._clock()
        return self.shown()

    def shown(self) -> str:
        """The code in groups of four, as the log shows it ("ABCD-EFGH-JKLM")."""
        code = self._code or ""
        return "-".join(code[i:i + 4] for i in range(0, len(code), 4))

    def active(self) -> bool:
        return self._code is not None and self._clock() - self._made < VALID_S

    def matches(self, typed: str) -> bool:
        """The code typed by the person (spaces, dashes and case do not matter), compared in constant time."""
        if not self.active() or not isinstance(typed, str):
            return False
        cleaned = "".join(c for c in typed.upper() if c.isalnum())
        return hmac.compare_digest(cleaned.encode(), (self._code or "").encode())

    def used(self) -> None:
        self._code = None
