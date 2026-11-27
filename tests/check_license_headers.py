# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Every first-party source file carries the one-line SPDX header that points to NOTICE (GPL-3.0 section 7: the additional terms, or a pointer to
them, in the relevant source files). The choice of the files and what is skipped (and why) is in tools/add_license_headers.py, which also adds a
missing header:  python -B tools/add_license_headers.py"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("add_license_headers", ROOT / "tools" / "add_license_headers.py")
alh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alh)

failed = []


def check(cond, msg):
    print(("ok: " if cond else "FAILED: ") + msg)
    if not cond:
        failed.append(msg)


files = alh.source_files(ROOT)
names = {f.relative_to(ROOT).as_posix() for f in files}
# the choice is not empty by mistake: one file of every kind is in it
for must in ("vedetta/app/main.py", "vedetta/app/frontend/ha/js/core.js", "vedetta/app/frontend/ha/css/10-base.css", "vedetta/app/templates/ha.html",
             "vedetta/run.sh", "vedetta/config.yaml", "vedetta/Dockerfile", "tools/add_license_headers.py", "tests/check_license_headers.py"):
    check(must in names, must + " is a first-party source file")
for never in ("vedetta/app/static/ha/icons.js", "vedetta/translations/en.yaml", "vedetta/app/locales/en/ha.json", "LICENSE", "NOTICE"):
    check(never not in names, never + " is skipped")
check(not any("/node_modules/" in "/" + n or n.startswith("tests/golden/") for n in names), "no third-party module and no golden file is in the choice")

missing = [n for n in sorted(names) if not alh.has_header(ROOT / n)]
check(not missing, "every first-party source file has the SPDX header (%d files; missing: %s)" % (len(names), ", ".join(missing[:10]) + (" ..." if len(missing) > 10 else "")))

# the header goes after a shebang and a Python encoding line, never twice
for text, suffix, first in (("#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nx = 1\n", ".py", 2), ("#!/bin/sh\necho\n", ".sh", 1), ("<!doctype html>\n<html>\n", ".html", 1),
                            ("x = 1\n", ".py", 0), ('@charset "utf-8";\na {}\n', ".css", 1)):
    once = alh.with_header(text, suffix)
    lines = once.splitlines()
    check(alh.TEXT in lines[first] and once.count(alh.TEXT) == 1 and alh.with_header(once, suffix) == once,
          "%s: the header is line %d, the lines before it stay first, a second run changes nothing" % (suffix, first + 1))
check(alh.with_header("a\r\nb\r\n", ".py").startswith("# " + alh.TEXT + "\r\na\r\n"), "a file with CRLF line ends keeps them")

print("FAILED: %d" % len(failed) if failed else "ALL OK")
sys.exit(1 if failed else 0)
