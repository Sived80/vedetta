"""devices.yaml is changed by read - modify - write sequences that run from threads (asyncio.to_thread) and from the loop at the same time. The file is replaced atomically (a reader never sees half a file) but
the SEQUENCE was not: two changes that read the same old file, then write one after the other, lose the first one (found by the global review: a scan result, or the name chosen by the user, could be
rolled back). Every modifying function now holds one lock for the whole sequence. This test makes the window wide (the read waits a little) and runs two threads on two cards: with the lock no change is lost."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import devices_config as dc  # noqa: E402

real_read = dc._read_yaml


def slow_read(text):
    data = real_read(text)
    time.sleep(0.002)          # the window between the read and the write, made wide on purpose
    return data


dc._read_yaml = slow_read


def fresh():
    tmp = Path(tempfile.mkdtemp())
    dc.CONFIG_DIR, dc.DEVICES_PATH = tmp, tmp / "devices.yaml"
    dc.add_devices([{"ip": "10.0.0.1", "id": "a"}, {"ip": "10.0.0.2", "id": "b"}, {"ip": "10.0.0.3", "id": "c"}])


lost = 0
for round_ in range(6):
    fresh()

    def work(device_id, field):
        for i in range(25):
            dc.set_override(device_id, field, f"v{i}")
            dc.update_scan_info(device_id, {"http_title": f"t{i}"})

    threads = [threading.Thread(target=work, args=("a", "focus_note")), threading.Thread(target=work, args=("b", "brand_user"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    cards = {d["id"]: d for d in dc.load_devices()}
    ok = (cards["a"].get("focus_note") == "v24" and cards["a"].get("scan_info") == {"http_title": "t24"}
          and cards["b"].get("brand_user") == "v24" and cards["b"].get("scan_info") == {"http_title": "t24"} and len(cards) == 3)
    lost += 0 if ok else 1
assert lost == 0, "a change was lost in %d of 6 rounds: the read-modify-write of devices.yaml is not serialised" % lost

# the same under the other modifying functions: rename, address, automatic name, removal and add at the same time
fresh()
errors: list = []


def mixed():
    try:
        for i in range(15):
            dc.update_device("a", f"Name {i}")
            dc.update_auto_name("b", f"Auto {i}", "mdns", force=True)
            dc.add_devices([{"ip": f"10.0.1.{i}", "id": f"n{i}"}])
    except Exception as exc:        # noqa: BLE001
        errors.append(exc)


def removing():
    try:
        for i in range(15):
            time.sleep(0.003)
            dc.remove_device(f"n{i}")
    except Exception as exc:        # noqa: BLE001
        errors.append(exc)


threads = [threading.Thread(target=mixed), threading.Thread(target=removing)]
for t in threads:
    t.start()
for t in threads:
    t.join()
cards = {d["id"]: d for d in dc.load_devices()}
assert not errors, errors
assert cards["a"]["name"] == "Name 14" and cards["b"]["name"] == "Auto 14" and "c" in cards, cards
print("TUTTO OK")
