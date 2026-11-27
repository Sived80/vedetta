# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The licence travels with the program (GPL-3.0 sections 4 and 6): the app folder that Home Assistant builds (vedetta/) has the same LICENSE and
NOTICE as the repository root, and the Dockerfile copies them into the image.
    python -B tests/check_license_in_app.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


for name in ("LICENSE", "NOTICE"):
    copy = ROOT / "vedetta" / name
    check(copy.is_file() and copy.read_bytes() == (ROOT / name).read_bytes(), "vedetta/%s is the same as the root %s" % (name, name))
docker = (ROOT / "vedetta" / "Dockerfile").read_text(encoding="utf-8")
check(any(line.startswith("COPY") and "LICENSE" in line and "NOTICE" in line for line in docker.splitlines()), "the Dockerfile copies LICENSE and NOTICE into the image")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
