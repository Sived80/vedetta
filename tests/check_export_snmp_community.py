# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The SNMP community is a password (it travels in clear on the network): never in an export. Both ways out hide it: the copy
for the person (export_zip._redact) and the masked one for the developer (Anonymizer.data, and the text of a log line)."""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_zip  # noqa: E402
from app.export.anonymize import Anonymizer  # noqa: E402

SECRET = "h0me-R34d-only"
settings = {"snmp_router": "192.168.1.1", "snmp_community": SECRET, "theme": "dark"}

mine = export_zip._redact(settings)
assert mine["snmp_community"] == "***" and mine["theme"] == "dark", mine

masked = Anonymizer().data(settings)
assert masked["snmp_community"] == "***", masked
assert SECRET not in str(masked)

line = Anonymizer().text(f"settings saved: community={SECRET} router 192.168.1.1")
assert SECRET not in line, line

assert export_zip._redact({"snmp_community": ""})["snmp_community"] == ""      # nothing written: nothing to hide
print("ALL OK")
