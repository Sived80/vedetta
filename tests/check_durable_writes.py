"""Files the app writes survive a power cut and a concurrent change. Found by the global review: write_atomic replaced the file without forcing the data to disk (a power cut could leave the new name with
an empty file: rename alone is atomic against a torn read, not durable; the sequence that is documented as crash-safe is temp file, fsync, rename, fsync of the folder: PostgreSQL's durable_rename
discussion and the crash-safe write primitives of several libraries; no systematic study exists and POSIX promises nothing); the compaction of the event journal wrote the file in place; and the mDNS memory
was serialised by a worker thread while the loop changed its dictionaries (one RuntimeError stopped the listener for good). The first start after an update numbers the cards of an old devices.yaml: it keeps a
copy of the old file and never stops the start."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import atomic  # noqa: E402
from app.scan import mdns_listener as ml  # noqa: E402
from app.storage import devices_config as dc  # noqa: E402
from app.storage import journal  # noqa: E402

tmp = Path(tempfile.mkdtemp())

# 1) write_atomic: the data is forced to disk BEFORE the rename, and the folder is synced after it (best effort)
calls: list = []
real_fsync, real_replace = os.fsync, os.replace
os.fsync = lambda fd: (calls.append("fsync"), real_fsync(fd))[1]
os.replace = lambda a, b: (calls.append("replace"), real_replace(a, b))[1]
try:
    atomic.write_atomic(tmp / "x.json", lambda f: f.write('{"a": 1}'), ".x-")
finally:
    os.fsync, os.replace = real_fsync, real_replace
assert calls[:2] == ["fsync", "replace"], "the data must be synced before the rename: %s" % calls
assert json.loads((tmp / "x.json").read_text(encoding="utf-8")) == {"a": 1}
assert not list(tmp.glob("*.tmp")), "no temporary file is left behind"

# 2) the compaction of the event journal goes through write_atomic
journal.PATH = tmp / "journal.jsonl"
journal.MAX_ENTRIES = 3
journal._entries.clear()
journal._loaded = True
used: list = []
real_wa = journal.write_atomic
journal.write_atomic = lambda *a, **k: (used.append(1), real_wa(*a, **k))[1]
try:
    for i in range(40):
        journal.add("normal", "journal.test", icon="x", n=i)
finally:
    journal.write_atomic = real_wa
assert used, "the journal was compacted in place, not atomically"
assert all(json.loads(line) for line in journal.PATH.read_text(encoding="utf-8").splitlines())

# 3) the mDNS memory: serialised from a COPY made in one step, written atomically, and a failure never raises
ml.STORE_PATH = tmp / "mdns_seen.json"
ml.by_mac.clear()
ml.by_ip.clear()
ml.by_mac["aa:bb:cc:00:00:01"] = {"name": "x", "services": [], "ip": "10.0.0.1", "seen": 1.0, "score": 1}
seen_payload: list = []
real_dump = ml.json.dump
ml.json.dump = lambda obj, fp, **k: (seen_payload.append(obj), real_dump(obj, fp, **k))[1]
try:
    ml._save()
finally:
    ml.json.dump = real_dump
assert seen_payload and seen_payload[0]["by_mac"] is not ml.by_mac and seen_payload[0]["by_ip"] is not ml.by_ip, "the dictionaries must be copied before they are serialised"
assert json.loads(ml.STORE_PATH.read_text(encoding="utf-8"))["by_mac"]["aa:bb:cc:00:00:01"]["name"] == "x"


def boom(obj, fp, **k):
    raise RuntimeError("dictionary changed size during iteration")


ml.json.dump = boom
try:
    ml._save()                       # must not raise: the listener would stop for good
finally:
    ml.json.dump = real_dump
assert not list(tmp.glob("mdns*.tmp")) and ml.STORE_PATH.exists()

# 4) the numbering of an old file at the start: a copy of the old file is kept, an unreadable file does not stop the start
dc.CONFIG_DIR, dc.DEVICES_PATH = tmp, tmp / "devices.yaml"
old = "devices:\n- {id: a, ip: 10.0.1.1, port: 80, adapter: generic}\n"
dc.DEVICES_PATH.write_text(old, encoding="utf-8")
assert dc.ensure_seq_safely() == 1
assert (tmp / "devices.yaml.bak").read_text(encoding="utf-8") == old and dc.load_devices()[0]["seq"] == 1
assert dc.ensure_seq_safely() == 0
dc.DEVICES_PATH.write_text("devices: [unclosed\n  - {", encoding="utf-8")
assert dc.ensure_seq_safely() == 0, "an unreadable file must not stop the start (it is told in the log)"
print("TUTTO OK")
