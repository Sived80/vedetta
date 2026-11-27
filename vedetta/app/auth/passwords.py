# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The password of the owner: its rules and its hash.

Hash: scrypt from the standard library (hashlib), with the minimum OWASP gives for it (Password Storage Cheat Sheet: N=2^17, r=8,
p=1, about 128 MiB), a random salt of 16 bytes, and a comparison in constant time. The stored text carries its parameters
("scrypt$17$8$1$<salt>$<hash>", base64 without padding), so a later version can raise them and re-hash at the next login.

Rules (NIST SP 800-63B rev. 4, a password used alone): at least 15 characters, at most 128, any character, no rule of composition;
refused when it is one of the most common passwords or the name of the app."""
import base64
import hashlib
import hmac
import os

LOG_N, R, P = 17, 8, 1
SALT_BYTES = 16
KEY_BYTES = 32
MAX_MEM = 256 * 1024 * 1024        # OpenSSL refuses more than 32 MiB unless told: N=2^17, r=8 needs 128 MiB
MIN_LENGTH, MAX_LENGTH = 15, 128
_COMMON = frozenset({
    "123456789012345", "1234567890123456", "passwordpassword", "password1234567", "qwertyuiopasdfg", "qwertyuiopasdfgh",
    "iloveyou12345678", "aaaaaaaaaaaaaaa", "000000000000000", "111111111111111", "passwordpassword1", "letmeinletmein1",
    "welcomewelcome1", "adminadminadmin", "administrator123", "homeassistant123", "homeassistant1234", "changemechangeme",
})


def problem(password: str) -> str | None:
    """Why the password cannot be used (a key of the texts: too_short, too_long, too_common), or None when it can."""
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        return "too_short"
    if len(password) > MAX_LENGTH:
        return "too_long"
    folded = password.strip().lower()
    few_letters = len(set(folded)) < 4                                    # "aaaaaaaaaaaaaaa", "abababab..."
    mostly_name = len(set(folded.replace("vedetta", ""))) < 4             # "vedettavedetta1"
    if folded in _COMMON or few_letters or mostly_name:
        return "too_common"
    return None


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text + "=" * (-len(text) % 4), validate=True)


def _scrypt(password: str, salt: bytes, log_n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** log_n, r=r, p=p, maxmem=MAX_MEM, dklen=KEY_BYTES)


def hash_password(password: str) -> str:
    """The stored form of a password (a new salt each time)."""
    salt = os.urandom(SALT_BYTES)
    return "scrypt$%d$%d$%d$%s$%s" % (LOG_N, R, P, _b64(salt), _b64(_scrypt(password, salt, LOG_N, R, P)))


def verify(password: str, stored: str) -> bool:
    """True when the password matches the stored form. A stored text that is not ours, or a password too long, is just False (no
    exception, no detail: the caller says only "wrong")."""
    if not isinstance(password, str) or len(password) > MAX_LENGTH or not isinstance(stored, str):
        return False
    try:
        kind, log_n, r, p, salt, digest = stored.split("$")
        log_n, r, p = int(log_n), int(r), int(p)
        if kind != "scrypt" or not (14 <= log_n <= 20 and 1 <= r <= 32 and 1 <= p <= 16):
            return False
        expected = _unb64(digest)
        return hmac.compare_digest(_scrypt(password, _unb64(salt), log_n, r, p), expected)
    except (ValueError, TypeError, MemoryError):
        return False


def needs_rehash(stored: str) -> bool:
    """True when the stored form uses parameters weaker than today's (it is hashed again after a good login)."""
    try:
        _, log_n, r, p, _, _ = stored.split("$")
        return (int(log_n), int(r), int(p)) < (LOG_N, R, P)
    except ValueError:
        return True
