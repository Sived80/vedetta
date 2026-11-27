# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Sealing a large export (export/report_crypto.seal) takes a moment, not minutes: the base64 text is cut into lines of 76 characters by
slicing. textwrap.wrap was used before: on one long word without spaces it copies the rest of the text at every line, so the time grew with
the square of the size (2 MB about 11 s on a PC, a 16 MB export many minutes on a small Home Assistant host). The lines stay exactly the
same as before, and the sealed file still opens with the private key.
    python tests/check_seal_speed.py"""
import base64
import os
import sys
import textwrap
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from nacl.public import PrivateKey, SealedBox  # noqa: E402

from app.export import report_crypto  # noqa: E402

key = PrivateKey.generate()
failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def body_of(sealed: bytes) -> str:
    text = sealed.decode("ascii")
    return text.split(report_crypto.BEGIN + "\n", 1)[1].split("\n" + report_crypto.END, 1)[0]


# 1) the same lines as textwrap gave, and the file opens
small = os.urandom(5000)
sealed = report_crypto.seal(small, bytes(key.public_key))
body = body_of(sealed)
check(all(len(line) == 76 for line in body.split("\n")[:-1]) and 0 < len(body.split("\n")[-1]) <= 76, "lines of 76 characters, the last one shorter")
check(body == "\n".join(textwrap.wrap(body.replace("\n", ""), 76)), "the same lines as textwrap.wrap gave")
check(SealedBox(key).decrypt(base64.b64decode(body.replace("\n", ""))) == small, "the sealed file opens with the private key")

# 2) a large export is sealed in a moment (textwrap: tens of seconds for 4 MB on a PC)
big = os.urandom(4 * 1024 * 1024)
started = time.perf_counter()
sealed = report_crypto.seal(big, bytes(key.public_key))
spent = time.perf_counter() - started
check(spent < 3.0, "4 MB sealed in a moment: %.2f s" % spent)
check(SealedBox(key).decrypt(base64.b64decode(body_of(sealed).replace("\n", ""))) == big, "and it opens")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
