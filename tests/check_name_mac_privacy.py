"""`name_mac` (the MAC that announced the name of a card) lives in the file of the devices. It is a MAC address, so it must not travel in an export in the clear: it is not part of the compact card
that the export carries, and anything that does carry a MAC goes through the anonymiser, which replaces it. The MAC below is made up."""
import json
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.export import anonymize  # noqa: E402

MAC = "c6:7e:11:22:33:44"
failed = []


def check(label, ok):
    if not ok:
        failed.append(label)


device = {"id": "d1", "ip": "10.0.0.5", "name": "name-a", "online": True, "extra": {}}
cfg = {"id": "d1", "ip": "10.0.0.5", "name": "name-a", "name_source": "dhcp", "name_mac": MAC, "focus": True, "focus_note": "note"}
card = json.dumps(ha_data.compact_device(device, cfg), default=str).lower()
check("the compact card of the export does not carry name_mac", MAC not in card and "name_mac" not in card)

masked = anonymize.Anonymizer().text("announced by " + MAC) if hasattr(anonymize, "Anonymizer") else None
check("the anonymiser replaces a MAC in a text (%r)" % masked, masked is not None and MAC not in masked)

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
