"""Encrypted report: the zip is sealed with the maintainer's public key (data/report_key.pub). Only the matching
private key, which never leaves the maintainer's computer, can open it, so the file can be attached to a public
GitHub issue. The result is plain text (base64 between two marker lines) so GitHub accepts it as a .txt file."""
import base64
import hashlib
import textwrap
from pathlib import Path

KEY_PATH = Path(__file__).resolve().parent / "data" / "report_key.pub"
BEGIN = "-----BEGIN VEDETTA REPORT-----"
END = "-----END VEDETTA REPORT-----"
INTRO = ("VEDETTA ENCRYPTED REPORT (v1)\n"
         "This file is encrypted: only the Vedetta maintainer can open it. IP addresses, MAC addresses and names\n"
         "were masked before it was created, and it is safe to attach to a public GitHub issue.\n")


class CryptoUnavailable(RuntimeError):
    pass


def public_key() -> bytes:
    return base64.b64decode(KEY_PATH.read_text(encoding="ascii").strip())


def fingerprint(key: bytes | None = None) -> str:
    """Short fingerprint to compare with the one published in the README."""
    digest = hashlib.sha256(key or public_key()).hexdigest()[:16]
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def seal(data: bytes, key: bytes | None = None) -> bytes:
    try:
        from nacl.public import PublicKey, SealedBox
    except ImportError as exc:       # never fall back to an unencrypted file
        raise CryptoUnavailable("PyNaCl is not installed") from exc
    sealed = SealedBox(PublicKey(key or public_key())).encrypt(data)
    body = "\n".join(textwrap.wrap(base64.b64encode(sealed).decode("ascii"), 76))
    return f"{INTRO}{BEGIN}\n{body}\n{END}\n".encode("ascii")
