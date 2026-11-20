"""settings.json is changed by read - modify - write sequences (update, mqtt_update, flows_update, sentinel_update, snmp_update) that run
from route threads at the same time. Each one re-reads the other keys and writes the whole file: without a lock two changes that read the
same old file lose the first one (an MQTT host, a poll interval, a router address rolled back). This test makes the window wide (the read
waits a little) and runs three threads on three different groups of keys: with the lock no change is lost. Invented values only."""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import settings  # noqa: E402

real_read = settings._read_file


def slow_read():
    data = real_read()
    time.sleep(0.002)          # the window between the read and the write, made wide on purpose
    return data


settings._read_file = slow_read
lost = 0
for round_ in range(4):
    settings.SETTINGS_PATH = Path(tempfile.mkdtemp()) / "settings.json"
    errors: list = []

    def run(job):
        try:
            for i in range(20):
                job(i)
        except Exception as exc:        # noqa: BLE001
            errors.append(exc)

    jobs = [lambda i: settings.update({"poll_interval": settings.POLL_INTERVALS[i % 2]}),
            lambda i: settings.mqtt_update({"mqtt_host": f"broker-{i}.example"}),
            lambda i: settings.snmp_update({"snmp_router": f"10.70.0.{i + 1}"})]
    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    ok = (settings.poll_interval() == settings.POLL_INTERVALS[1] and settings.mqtt_load()["mqtt_host"] == "broker-19.example"
          and settings.snmp_load()["snmp_router"] == "10.70.0.20")
    lost += 0 if ok else 1
assert lost == 0, "a change was lost in %d of 4 rounds: the read-modify-write of settings.json is not serialised" % lost
print("ALL OK")
