"""The ready-made Home Assistant blueprints (blueprints/automation/vedetta/*.yaml) stay in step with the events Vedetta fires
(app/ha/ha_notify.py): every file parses (with !input), has the keys Home Assistant needs and the current syntax (triggers/actions),
says first that the events must be turned on (with the label the page shows), listens only to event types of ha_notify.EVENT_TYPES,
reads only keys that event_data produces, and uses only inputs it declares (and declares none it does not use). The README offers
each one with the import badge of My Home Assistant.
    python tools/run_test.py check_blueprints.py"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

import yaml

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app.ha import ha_notify  # noqa: E402

FOLDER = ROOT / "blueprints" / "automation" / "vedetta"
EXPECTED = {"new_device.yaml": {"vedetta_new_device"}, "device_down.yaml": {"vedetta_device_down", "vedetta_device_back"}}
EVENTS_LABEL = json.loads((ROOT / "vedetta" / "app" / "locales" / "en" / "ha.json").read_text(encoding="utf-8"))["js.ha.alerts.events"]
DATA_RE = re.compile(r"trigger\.event\.data\.(\w+)")


class Input(str):
    """A !input reference: the name of the input."""


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("!input", lambda loader, node: Input(loader.construct_scalar(node)))


def walk(obj):
    """Every value of a parsed file (dict values and list items, nested)."""
    yield obj
    children = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, list) else ()
    for child in children:
        yield from walk(child)


def produced_keys(kind: str) -> set:
    ev = {"kind": kind, "card": "c1", "params": {"label": "L", "ip": "192.0.2.1", "away_s": 60}}
    return set(ha_notify.event_data(ev))


KEYS_OF = {ha_notify.EVENT_TYPES[k]: produced_keys(k) for k in ha_notify.EVENT_TYPES}
readme = (ROOT / "README.md").read_text(encoding="utf-8")
assert sorted(p.name for p in FOLDER.glob("*.yaml")) == sorted(EXPECTED), "one test entry per blueprint"

for name, events in EXPECTED.items():
    path = FOLDER / name
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=Loader)       # noqa: S506  SafeLoader with one extra tag
    bp = doc["blueprint"]
    rel = path.relative_to(ROOT).as_posix()
    assert bp["name"].startswith("Vedetta: ") and bp["domain"] == "automation", name
    assert bp["source_url"] == f"https://github.com/Sived80/vedetta/blob/main/{rel}", (name, bp["source_url"])
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", bp["homeassistant"]["min_version"]), name
    assert bp["homeassistant"]["min_version"] >= "2024.10.0", "triggers:/trigger: event need 2024.10"
    first_line = bp["description"].splitlines()[0]
    assert f'"{EVENTS_LABEL}"' in first_line and first_line.startswith("Turn on"), (name, first_line)
    assert {"triggers", "actions"} <= doc.keys() and not {"trigger", "action", "condition"} & doc.keys(), "current syntax only"
    assert all(t["trigger"] == "event" for t in doc["triggers"]), name
    fired = {t["event_type"] for t in doc["triggers"]}
    assert fired == events and fired <= set(ha_notify.EVENT_TYPES.values()), (name, fired)
    texts = [v for v in walk({k: v for k, v in doc.items() if k != "blueprint"}) if isinstance(v, str) and not isinstance(v, Input)]
    used_keys = {k for t in texts for k in DATA_RE.findall(t)}
    for event in fired:
        missing = used_keys - KEYS_OF[event] - ({"minutes"} if "minutes" in used_keys else set())
        assert not missing, (name, event, "keys the event does not carry", missing)
    if "minutes" in used_keys:
        assert "minutes" in KEYS_OF["vedetta_device_back"]
    assert {"brand", "type", "kind"} & used_keys or name != "new_device.yaml", "the new device says what it is"
    declared = set(bp["input"])
    used_inputs = {str(v) for v in walk(doc) if isinstance(v, Input)}
    assert used_inputs == declared, (name, "used", used_inputs, "declared", declared)
    assert any("notify" == d.get("type") and d.get("domain") == "mobile_app" for d in doc["actions"] if isinstance(d, dict)), name
    raw = path.read_text(encoding="utf-8")
    assert "riscansione" not in raw.lower() and "rescan" not in raw.lower()
    badge = "https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=" + quote(bp["source_url"], safe="")
    assert badge in readme, (name, "import badge missing in the README", badge)
assert readme.count("https://my.home-assistant.io/badges/blueprint_import.svg") == len(EXPECTED)
print("ok: blueprints in step with the events")
