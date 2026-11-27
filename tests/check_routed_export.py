# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0 step P11: the counts of the ping sweep behind the router in both exports (export_zip.step_counts, which the export window takes too):
"routed" = the networks of the last sweep, the sweeps of a network, the addresses asked, those that answered, those whose MAC Home Assistant
said, the new devices and the seconds. Numbers only: never an address, a MAC or a name.
    python tests/check_routed_export.py"""
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import routedwatch  # noqa: E402
from app.export import export_zip  # noqa: E402

routedwatch._counts.update(networks=2, sweeps=7, asked=508, answered=33, with_mac=12, new=3, seconds=41.27)
got = export_zip.step_counts()["routed"]
assert got == {"networks": 2, "sweeps": 7, "asked": 508, "answered": 33, "with_mac": 12, "new": 3, "seconds": 41.3}, got
assert all(isinstance(v, (int, float)) for v in got.values()) and "." not in json.dumps(got).replace("41.3", ""), "numbers only"
routedwatch.reset_counts()
assert export_zip.step_counts()["routed"] == {"networks": 0, "sweeps": 0, "asked": 0, "answered": 0, "with_mac": 0, "new": 0, "seconds": 0.0}
print("check_routed_export: ok")
