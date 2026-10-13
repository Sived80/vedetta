"""A card number: a progressive number given by Vedetta to every card, never reused, kept in devices.yaml. It tells identical cards apart (five Shelly with the same model name) and works for
phones too (a private MAC is no identity). Shown only when a card has a twin. Study: a surrogate key is meaningless on purpose and insulates the relations from changes of the data (the MAC is an
attribute, not the key). The twins: same name and brand and type."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import twins  # noqa: E402
from app.storage import devices_config as dc  # noqa: E402

tmp = Path(tempfile.mkdtemp())
dc.CONFIG_DIR = tmp
dc.DEVICES_PATH = tmp / "devices.yaml"

# new cards are numbered 1, 2, 3...
added = dc.add_devices([{"ip": "10.0.0.1"}, {"ip": "10.0.0.2"}, {"ip": "10.0.0.3"}])
assert [d["seq"] for d in added] == [1, 2, 3], added
# a number is never reused, even when the highest card is removed
assert dc.remove_device(added[2]["id"])
assert [d["seq"] for d in dc.add_devices([{"ip": "10.0.0.4"}])] == [4]
assert [d["seq"] for d in dc.load_devices()] == [1, 2, 4]

# an old file without numbers: they are given once, in the order of the file, and kept
dc.DEVICES_PATH.write_text("devices:\n- {id: a, ip: 10.0.1.1, port: 80, adapter: generic}\n- {id: b, ip: 10.0.1.2, port: 80, adapter: generic}\n", encoding="utf-8")
assert dc.ensure_seq() == 2 and [d["seq"] for d in dc.load_devices()] == [1, 2]
assert dc.ensure_seq() == 0, "already numbered: nothing is written"
assert [d["seq"] for d in dc.add_devices([{"ip": "10.0.1.3"}])] == [3]
assert dc.update_ip("a", "10.0.1.9") == "10.0.1.1" and {d["id"]: d["seq"] for d in dc.load_devices()}["a"] == 1, "the number follows the card, not the address"

# the twins: only cards that look the same get a number shown
cards = [{"id": "1", "seq": 1, "name": "Shelly SHDM-2", "brand": "Shelly", "type": "iot"}, {"id": "2", "seq": 2, "name": "shelly shdm-2", "brand": "Shelly", "type": "iot"},
         {"id": "3", "seq": 5, "name": "Shelly SHDM-2", "brand": "Shelly", "type": "iot"}, {"id": "4", "seq": 6, "name": "Cucina", "brand": "Shelly", "type": "iot"},
         {"id": "5", "seq": 7, "name": "Pixel", "brand": "Google", "type": "phone"}, {"id": "6", "seq": 8, "name": "Pixel", "brand": "Google", "type": "phone"},
         {"id": "7", "name": "Shelly SHDM-2", "brand": "Shelly", "type": "iot"}]
assert twins.twin_numbers(cards) == {"1": 1, "2": 2, "3": 5, "5": 7, "6": 8}, twins.twin_numbers(cards)
assert twins.twin_numbers([]) == {} and twins.twin_numbers([{"id": "x", "seq": 1, "name": "A"}]) == {}
print("TUTTO OK")
