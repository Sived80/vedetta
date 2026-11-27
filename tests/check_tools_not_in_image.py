# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Nmap and arp-scan are not in the published image (decision C of 20/11): the Nmap licence (NPSL, section 3) counts a program made to run
Nmap and read its output as a derivative work, and a derivative work distributed WITH Nmap must follow the NPSL. Since 0.12.0 the signed
images on ghcr.io carried Nmap: now the image is built without the two programs and Home Assistant installs them from Alpine Linux when
the app starts (as it did on its own build up to 0.11). Checks: 1) the Dockerfile installs neither; 2) run.sh installs both from Alpine
before starting the server, retries, and starts the server anyway; 3) the notices say how they arrive, and nothing claims the opposite.
    python tests/check_tools_not_in_image.py"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


docker = read("vedetta", "Dockerfile")
apk_lines = [line for line in docker.splitlines() if "apk add" in line]
check(not any(re.search(r"\b(nmap|nmap-scripts|arp-scan)\b", line) for line in apk_lines), "the image does not install nmap or arp-scan: " + "; ".join(apk_lines))

run = read("vedetta", "run.sh")
install = run.find("apk add")
start = run.find("python -m uvicorn")
check(install != -1 and re.search(r"apk add[^\n]*\bnmap\b[^\n]*\bnmap-scripts\b[^\n]*\barp-scan\b", run) is not None,
      "run.sh installs nmap, nmap-scripts and arp-scan from Alpine")
check(-1 < install < start, "before the server starts")
check(re.search(r"command -v nmap", run) is not None and re.search(r"command -v arp-scan", run) is not None, "only when they are missing (a restart of the same container does not download them again)")
check(re.search(r"for \w+ in 1 2 3", run) is not None, "with a few retries (the network may come up after the app)")
block = run[install - 400:start]
check(not re.search(r"^\s*(bashio::exit\S*|exit)\b", block, re.M) and re.search(r"while sleep \d+", block) is not None,
      "a failed install does not stop the app: the server starts and the install is tried again later in the background")

notices = read("THIRD_PARTY_NOTICES.md")
check("when the app starts" in notices and "not part of the published image" in notices, "the notices say they are installed when the app starts and are not in the image")
flat = " ".join(notices.split())
check("built on your own Home Assistant" not in flat and "does not publish a ready-made image" not in flat, "no old sentence about the image built on your Home Assistant")
readme = read("README.md")
check("installed from Alpine on your Home Assistant when the app starts" in readme, "the README says the same, in one line")

print("ALL OK" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
