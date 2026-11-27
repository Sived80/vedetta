# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 (Docker): the one-time code of the first start is written in the log (auth_routes.announce_setup) and the log goes in the
export. The code must never leave the container in an export, neither the one for me (plain zip) nor the one for the developer:
the line stays (it says when the first start happened) with the code replaced by XXXX-XXXX-XXXX, also in the rotated logs, with
or without a period. Invented codes only.
    python tools/run_test.py check_export_setup_code.py"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_gather as G, export_zip as legacy  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


CODES = ("QWER-TY23-UPAS", "ZZZZ-9999-HJKL")
tmp = Path(tempfile.mkdtemp())
now = datetime.now(timezone.utc).astimezone()
stamp = (now - timedelta(hours=2)).isoformat(timespec="seconds")
text = "".join(f"{stamp}\tWARNING\tFIRST SETUP: open the Vedetta page (port 8765) and choose the password. "
               f"One-time code, valid 60 minutes: {c}\n" for c in CODES) + f"{stamp}\tINFO\tan ordinary line\n"
for name in ("dashboard.log", "dashboard.log.1"):
    (tmp / name).write_text(text, encoding="utf-8")


def clean(kept: str, where: str) -> None:
    check(not any(c in kept for c in CODES), f"{where}: no one-time code is left")
    check(kept.count("One-time code, valid 60 minutes: XXXX-XXXX-XXXX") == 2, f"{where}: the lines stay, with a placeholder")
    check("an ordinary line" in kept, f"{where}: the other lines are untouched")


for dest in ("me", "dev"):
    for period in (False, True):
        p = G.Prepared(dest)
        if period:
            p.since, p.until = (now - timedelta(days=1)).timestamp(), now.timestamp()
        for name in ("dashboard.log", "dashboard.log.1"):
            G._collect_data_file(p, tmp / name)
            clean(p.files[f"data/{name}"][1], f"export for {dest}, {'with' if period else 'without'} a period, {name}")
        p.close()

# the older zip (build_zip) copies the log tail as bytes: the same rule
class FakeZip:
    def __init__(self) -> None:
        self.files = {}

    def put(self, name, content, text=True) -> None:
        self.files[name] = content


z = FakeZip()
legacy._put_one_data_file(z, tmp / "dashboard.log")
stored = z.files["data/dashboard.log"]
clean(stored.decode() if isinstance(stored, bytes) else stored, "older zip")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
