"""The notification of a new device says its brand and its type, in the language of Home Assistant (app/ha/ha_notify.py lines):
the finer type when it has a translated name ("presa"), else the group when it has one, else nothing; a brand or a type that Vedetta
does not know is left out, never written as "None". Down and back keep their short line. Names already exist in the five languages.
    python tests/check_notify_details.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n  # noqa: E402
from app.ha import ha_notify  # noqa: E402


def new(**facts):
    return {"kind": "new", "card": "02:00:00:00:00:09", "params": {"label": "Kitchen plug", "ip": "192.0.2.9", **facts}}


# 1) brand and finer type, in each language
assert ha_notify.lines([new(brand="Acme", type="iot", kind="plug")], "en") == ["New device on the network: Kitchen plug (192.0.2.9) · Acme · plug"]
assert ha_notify.lines([new(brand="Acme", type="iot", kind="plug")], "it") == ["Nuovo dispositivo in rete: Kitchen plug (192.0.2.9) · Acme · presa"]
for lang in ("en", "it", "de", "cs", "fr"):
    line = ha_notify.lines([new(brand="Acme", type="iot", kind="plug")], lang)[0]
    assert line.endswith(" · Acme · " + i18n.translate(lang, "kind.plug")), (lang, line)
    assert "kind." not in line and "None" not in line, (lang, line)

# 2) no translated name for the finer type: the group's name; neither: only the brand
assert ha_notify.lines([new(brand="Acme", type="router", kind="no_such_kind")], "en")[0].endswith(" · Acme · router")
assert ha_notify.lines([new(brand="Acme", type="iot", kind=None)], "en")[0].endswith("(192.0.2.9) · Acme")

# 3) nothing known: the line of 1.0.2, unchanged
assert ha_notify.lines([new()], "en") == ["New device on the network: Kitchen plug (192.0.2.9)"]
assert ha_notify.lines([new(brand=None, type=None, kind=None)], "en") == ["New device on the network: Kitchen plug (192.0.2.9)"]
assert ha_notify.lines([new(type="iot", kind="plug")], "en") == ["New device on the network: Kitchen plug (192.0.2.9) · plug"]

# 4) down and back keep their line
down = {"kind": "down", "card": "nas", "params": {"label": "NAS", "ip": "192.0.2.5", "brand": "Acme", "type": "server", "kind": "nas"}}
assert ha_notify.lines([down], "en") == ["NAS (192.0.2.5) is not answering"]

print("check_notify_details: OK")
