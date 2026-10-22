"""The load of the system under the app (scan/host_load.py): the pressure stall information of the kernel (/proc/pressure/{cpu,io,memory}, the "some" line, average of the last 60 s) read without any permission, a
traffic light for the heavy background work (busy: which resource is over its limit, or None) and a sampler that keeps the last samples and writes one line to the log each hour, so the limits can be tuned on real
days. Seen on the Proxmox history of 22 Oct: the disk of the host is saturated for about 22 minutes every three hours (backup); the CPU never. No address, no name: numbers only. Nothing readable, nothing blocked."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import host_load as hl  # noqa: E402

# --- the format of the kernel: avg60 of the line "some"
assert hl.parse("some avg10=0.51 avg60=2.46 avg300=3.11 total=7130673515\nfull avg10=0.59 avg60=9.35 avg300=2.96 total=6843996080\n") == 2.46
assert hl.parse("some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n") == 0.0
for bad in ("", "full avg10=1 avg60=2 avg300=3 total=4", "some avg10=x avg60=y", "garbage", None):
    assert hl.parse(bad) is None, bad

# --- read: one value per resource from a folder; a missing or unreadable file leaves the resource out; no folder at all is None
tmp = Path(tempfile.mkdtemp())
(tmp / "cpu").write_text("some avg10=0.51 avg60=0.40 avg300=0.39 total=1\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n")
(tmp / "io").write_text("some avg10=61.0 avg60=52.5 avg300=3.11 total=1\nfull avg10=59.0 avg60=50.1 avg300=2.96 total=1\n")
assert hl.read(str(tmp)) == {"cpu": 0.4, "io": 52.5}, hl.read(str(tmp))
assert hl.read(str(tmp / "nowhere")) is None
(tmp / "memory").write_text("junk")
assert hl.read(str(tmp)) == {"cpu": 0.4, "io": 52.5}, "a file that cannot be understood is left out"

# --- the traffic light: over the limit of one resource, its name; at the limit is still free; without readings, free
lim = hl.LIMITS
assert lim["io"] > 0 and lim["cpu"] > 0 and lim["memory"] > 0
assert hl.busy({"io": lim["io"] + 0.1, "cpu": 0.0}) == "io" and hl.busy({"io": lim["io"], "cpu": lim["cpu"], "memory": lim["memory"]}) is None, "at the limit is free"
assert hl.busy({"cpu": lim["cpu"] + 1}) == "cpu" and hl.busy({"memory": lim["memory"] + 1}) == "memory"
assert hl.busy({"io": 1.0, "cpu": 1.0, "memory": 1.0}) is None and hl.busy({}) is None and hl.busy(None) is None, "no reading: nothing is blocked"

# --- a deferral is counted and told; the count and the last reason are what the export says
hl._deferred = {"count": 0, "last_reason": None, "last_at": None}
hl.note_deferred("io", now=1000.0)
hl.note_deferred("cpu", now=1010.0)
assert hl._deferred == {"count": 2, "last_reason": "cpu", "last_at": 1010.0}

# --- the sampler: a ring of the last samples; the line of the log once an hour (silent the first time: the clock starts), with the highest of each resource and the deferrals of the hour
hl._samples.clear(); hl._hour = {"max": {}, "deferred_at_start": 0, "started": None}
hl._deferred = {"count": 5, "last_reason": None, "last_at": None}
LINES: list = []
hl.logger.info = lambda msg, *a, **k: LINES.append(msg % a if a else msg)
readings = iter([{"io": 2.0, "cpu": 0.1}, {"io": 40.0, "cpu": 0.3}, {"io": 3.0, "cpu": 0.2, "memory": 0.0}])
hl.sample_once(0.0, reader=lambda: next(readings))
assert not LINES and len(hl._samples) == 1
hl._deferred["count"] = 7
hl.sample_once(1800.0, reader=lambda: next(readings))
assert not LINES, "not yet an hour"
hl.sample_once(3600.0, reader=lambda: next(readings))
assert LINES == ["Host load: in the last hour the highest pressure was io 40.0%, cpu 0.3%, memory 0.0%; heavy scans put off: 2"], LINES
assert [round(s["io"], 1) for s in hl._samples] == [2.0, 40.0, 3.0]
for i in range(hl.KEEP_SAMPLES + 20):
    hl.sample_once(4000.0 + i, reader=lambda: {"io": 1.0})
assert len(hl._samples) == hl.KEEP_SAMPLES, "the ring does not grow"
assert len(LINES) == 1, ("after the line the hour starts again: no second line within the hour", LINES)
LINES.clear()
hl.sample_once(9000.0, reader=lambda: None)
assert not LINES and hl._samples[-1] == {"t": 9000.0}, "nothing readable: a sample without values, no line, no error"

# --- what the export says: availability, limits, the last reading, the deferrals and the last samples; numbers only
hl._samples.clear()
for i, v in enumerate((1.0, 2.0, 30.0)):
    hl._samples.append({"t": 100.0 + i, "io": v, "cpu": 0.1})
hl._deferred = {"count": 3, "last_reason": "io", "last_at": 5000.0}
part = hl.manifest_part()
assert part["limits"] == hl.LIMITS and part["deferred"] == {"count": 3, "last_reason": "io", "last_at": 5000.0} and part["last"]["io"] == 30.0, part
assert [s["io"] for s in part["samples"]] == [1.0, 2.0, 30.0] and part["available"] is True
hl._samples.clear()
assert hl.manifest_part()["available"] is False and hl.manifest_part()["samples"] == []
assert set(part) == {"available", "limits", "last", "deferred", "samples"}

# --- the background task: it starts, samples, stops when asked; and does nothing if the kernel gives nothing
async def lifecycle():
    hl.SAMPLE_S = 0.01
    hl._reader = lambda: {"io": 1.0}
    hl._samples.clear()
    hl.start()
    await asyncio.sleep(0.15)
    await hl.stop()
    assert hl._task is None and len(hl._samples) >= 3, len(hl._samples)
    count = len(hl._samples)
    await asyncio.sleep(0.05)
    assert len(hl._samples) == count, "stopped means stopped"

asyncio.run(lifecycle())
print("check_host_load OK")
