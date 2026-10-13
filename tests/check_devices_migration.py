"""A devices.yaml written by an older version, or edited by hand, must come through the numbering of the cards (ensure_seq_safely, at every start) with nothing lost: every field of every card is kept (user
choices, notes, scan results, fields this version does not know), the old file is kept as .bak, a second start changes nothing, and a file that is empty, has no list of cards or cannot be read never stops the
start and is never overwritten."""
import copy
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config as dc  # noqa: E402

tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"
BAK = tmp / "devices.yaml.bak"

OLD = {"devices": [
    {"id": "cam-1", "name": "Camera ingresso", "ip": "10.0.0.20", "port": 80, "adapter": "generic", "type": "camera", "brand": "Milesight", "mac": "aa:bb:cc:dd:ee:01",
     "notes": "garage, \u00e8 l'unica con POE", "hidden": False, "no_touch": "on", "future_field": {"a": [1, 2, 3], "b": None},
     "scan_info": {"ports": [{"port": 80, "label": "nginx", "confirmed": True}, {"port": 554, "label": "rtsp"}], "http_title": "Web UI", "scanned_at": 1700000000}},
    {"id": "old-shelly", "ip": "10.0.0.21", "port": 80, "adapter": "shelly_gen1"},
    {"id": "tv", "name": "TV salotto", "ip": "10.0.0.22", "port": 8008, "adapter": "generic", "type_source": "user", "type": "tv"},
]}


def write(text: str) -> None:
    dc.DEVICES_PATH.write_text(text, encoding="utf-8", newline="")
    if BAK.exists():
        BAK.unlink()


def numbered(cards):
    return [{k: v for k, v in c.items() if k != "seq"} for c in cards]


# 1) an old file: every field survives, the numbers follow the order of the file, the old file is kept
old_text = yaml.safe_dump(OLD, allow_unicode=True, sort_keys=False)
write(old_text)
assert dc.ensure_seq_safely() == 3
cards = dc.load_devices()
assert [c["seq"] for c in cards] == [1, 2, 3]
assert numbered(cards) == OLD["devices"], "a field was lost or changed by the numbering"
assert BAK.read_text(encoding="utf-8") == old_text, "the old file must be kept as it was"

# 2) a second start changes nothing (the file is not even rewritten)
before = dc.DEVICES_PATH.read_bytes()
mtime = dc.DEVICES_PATH.stat().st_mtime_ns
assert dc.ensure_seq_safely() == 0
assert dc.DEVICES_PATH.read_bytes() == before and dc.DEVICES_PATH.stat().st_mtime_ns == mtime

# 3) the same with Windows line ends, written by hand
write(old_text.replace("\n", "\r\n"))
assert dc.ensure_seq_safely() == 3 and numbered(dc.load_devices()) == OLD["devices"]

# 4) a half-numbered file: only the cards without a number get one, above the highest
half = copy.deepcopy(OLD)
half["devices"][1]["seq"] = 7
write(yaml.safe_dump(half, allow_unicode=True, sort_keys=False))
assert dc.ensure_seq_safely() == 2
assert [c["seq"] for c in dc.load_devices()] == [8, 7, 9], [c["seq"] for c in dc.load_devices()]

# 5) the file that cannot be a list of cards never stops the start and is never overwritten
for text in ("", "devices:\n", "devices: []\n", "just text\n", "- a\n- b\n", "devices: {a: 1}\n", "{not yaml: [", "devices:\n- 5\n- {id: x}\n"):
    write(text)
    assert dc.ensure_seq_safely() == 0, text
    assert dc.DEVICES_PATH.read_text(encoding="utf-8") == text, "a file that cannot be numbered must stay as it was: %r" % text
print("TUTTO OK")
