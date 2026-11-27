# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.1 (Docker): the files of the login never leave the container in an export, neither the one for me nor the one for the developer:
/data/auth.json (the password hash), /data/sessions.json (the digests of the open sessions) and their temporary copies while they are
written. The export copies the data folder file by file and skips the names that may hold a credential: these two did not match any
word of that list ("auth", "sessions"). Invented values only.
    python tools/run_test.py check_auth_not_exported.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_gather, export_zip  # noqa: E402

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


folder = Path(tempfile.mkdtemp())
for name, text in (("auth.json", '{"password": "scrypt$17$8$1$c2FsdA$aGFzaA", "changed_at": 1}'), ("sessions.json", '{"%s": {"created": 1, "seen": 1}}' % ("a" * 64)),
                   (".auth-x1y2.tmp", "{}"), (".sessions-x1y2.tmp", "{}"), ("devices.json", "[]")):
    (folder / name).write_text(text, encoding="utf-8")

for name in ("auth.json", "sessions.json", ".auth-x1y2.tmp", ".sessions-x1y2.tmp"):
    f = folder / name
    check(export_zip._skip_data_file(f), "the export for me skips %s" % name)
    check(export_gather._is_skipped_data_file(f), "the export for the developer skips %s" % name)
check(not export_zip._skip_data_file(folder / "devices.json") and not export_gather._is_skipped_data_file(folder / "devices.json"),
      "an ordinary data file is still exported")

if failed:
    print("%d FAILED" % failed)
    sys.exit(1)
print("ALL OK")
