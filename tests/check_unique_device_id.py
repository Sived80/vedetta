"""Characterization of the id of a new card, before the work on more networks (the id stays `scan-<ip>` because the networks may not overlap, so an address never repeats):
the id is made from the address, `-2`, `-3`... are added while it is taken, an explicit id is kept (and gets the same suffixes), the set of taken ids is not changed.
    python tests/check_unique_device_id.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage.devices_config import _unique_device_id  # noqa: E402

assert _unique_device_id({"ip": "10.0.0.20"}, set()) == "scan-10-0-0-20"
assert _unique_device_id({"ip": "10.0.0.20"}, {"scan-10-0-0-20"}) == "scan-10-0-0-20-2"
taken = {"scan-10-0-0-20", "scan-10-0-0-20-2"}
assert _unique_device_id({"ip": "10.0.0.20"}, taken) == "scan-10-0-0-20-3"
assert taken == {"scan-10-0-0-20", "scan-10-0-0-20-2"}, "the set of taken ids must not change"

# an explicit id wins over the address, and gets the same suffixes
assert _unique_device_id({"ip": "10.0.0.20", "id": "lamp"}, set()) == "lamp"
assert _unique_device_id({"ip": "10.0.0.20", "id": "lamp"}, {"lamp"}) == "lamp-2"
# an empty id counts as missing
assert _unique_device_id({"ip": "10.0.0.20", "id": ""}, set()) == "scan-10-0-0-20"

# addresses of different networks never give the same id (the networks may not overlap)
ids = {_unique_device_id({"ip": ip}, set()) for ip in ("10.0.0.20", "10.0.20.20", "192.168.50.20", "10.0.2.0")}
assert len(ids) == 4, ids

print("check_unique_device_id: ok")
