"""Where does the time go? A measured workload on REAL data with the network replaced by instant answers (so what is measured is our code, not the network):
  cycle  - DeviceState.poll_once repeated N times on the devices and the history database of an export "for me" (probe of every device, results applied, presence and MAC layer written);
  export - the build of the export file for analysis on the same data.
Standard library only (cProfile, pstats, tracemalloc). Prints the time per cycle, the memory peak and the functions of the application that cost most (cumulative time); writes a JSON baseline.
    python tools/runtime_profile.py EXPORT.zip [--cycles 30] [--out baseline.json] [--top 14]
The numbers are for THIS machine: compare before and after a change on the same machine, never with the Home Assistant host."""
import argparse
import asyncio
import cProfile
import io
import json
import os
import pstats
import statistics
import sys
import tempfile
import time
import tracemalloc
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def top_functions(prof: cProfile.Profile, n: int) -> list:
    st = pstats.Stats(prof, stream=io.StringIO())
    rows = []
    for (path, line, name), (cc, nc, tt, ct, _callers) in st.stats.items():
        if "vedetta" in path.replace("\\", "/") and "app" in path.replace("\\", "/"):
            rows.append({"function": "%s:%s" % (Path(path).name, name), "calls": nc, "total_s": round(tt, 4), "cumulative_s": round(ct, 4)})
    rows.sort(key=lambda r: -r["cumulative_s"])
    return rows[:n]


def top_own_time(prof: cProfile.Profile, n: int) -> list:
    """The functions (ours or a library's) where the time is really spent, by their own time."""
    st = pstats.Stats(prof, stream=io.StringIO())
    rows = [{"function": "%s:%s" % (Path(path).name, name), "calls": nc, "own_s": round(tt, 3)} for (path, line, name), (cc, nc, tt, ct, _c) in st.stats.items()]
    rows.sort(key=lambda r: -r["own_s"])
    return rows[:n]


async def run_cycles(cycles: int, top: int) -> dict:
    from app.scan import latency, probe
    from app.state import DeviceState
    from app.storage import devices_config

    async def fake_adapter(ip, port):
        return {"online": True}
    for k in list(probe.ADAPTERS):
        probe.ADAPTERS[k] = fake_adapter

    async def no_latency(targets):
        return {}
    latency.measure_many = no_latency
    st = DeviceState()
    await st.load_history()
    devices = devices_config.load_devices()

    from app.storage.history import history
    known = {r["ip"]: m for m, r in history.known_all().items() if r.get("ip")}          # the MACs the real service saw at those addresses

    async def fake_arp(max_age):
        return {d["ip"]: {"mac": known.get(d["ip"]) or d.get("mac") or "02:00:00:00:%02x:%02x" % (i // 256, i % 256)} for i, d in enumerate(devices)}
    st._arp_by_ip = fake_arp
    for _ in range(2):                                         # warm-up: first cards, caches
        await st.poll_once()
    times = []
    prof = cProfile.Profile()
    tracemalloc.start()
    for _ in range(cycles):
        t0 = time.perf_counter()
        prof.enable()
        await st.poll_once()
        prof.disable()
        times.append(time.perf_counter() - t0)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return {"devices": len(devices), "cycles": cycles, "cycle_ms_median": round(1000 * statistics.median(times), 1), "cycle_ms_max": round(1000 * max(times), 1),
            "cycle_ms_p90": round(1000 * sorted(times)[int(0.9 * len(times))], 1), "memory_peak_mb": round(peak / 1e6, 1), "top": top_functions(prof, top), "top_own": top_own_time(prof, 8)}


def run_export(top: int) -> dict:
    from app.export import export_engine
    prof = cProfile.Profile()
    t0 = time.perf_counter()
    prof.enable()
    try:
        data = export_engine.build("me")
        size = len(data)
        err = None
    except Exception as exc:  # noqa: BLE001
        size, err = 0, repr(exc)[:200]
    prof.disable()
    return {"seconds": round(time.perf_counter() - t0, 2), "bytes": size, "error": err, "top": top_functions(prof, top)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--cycles", type=int, default=30)
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=14)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="rt_"))
    with zipfile.ZipFile(args.export) as z:
        for n in z.namelist():
            if n.startswith("data/") and not n.endswith("/"):
                (tmp / Path(n).name).write_bytes(z.read(n))
    os.environ["VEDETTA_DATA_DIR"] = str(tmp)
    sys.path.insert(0, str(REPO / "vedetta"))
    loop = asyncio.new_event_loop()
    cycle = loop.run_until_complete(run_cycles(args.cycles, args.top))
    export = run_export(args.top)
    result = {"python": sys.version.split()[0], "platform": sys.platform, "cycle": cycle, "export": export}
    print("CYCLE  devices=%d  median %.1f ms  p90 %.1f ms  max %.1f ms  memory peak %.1f MB" % (cycle["devices"], cycle["cycle_ms_median"], cycle["cycle_ms_p90"], cycle["cycle_ms_max"], cycle["memory_peak_mb"]))
    for r in cycle["top"]:
        print("   %7.3f s cum  %7.3f s own  %7d calls  %s" % (r["cumulative_s"], r["total_s"], r["calls"], r["function"]))
    print("  where the time is really spent (own time, any file):")
    for r in cycle["top_own"]:
        print("   %7.3f s  %7d calls  %s" % (r["own_s"], r["calls"], r["function"]))
    print("EXPORT %.2f s  %d bytes  %s" % (export["seconds"], export["bytes"], export["error"] or ""))
    for r in export["top"]:
        print("   %7.3f s cum  %7.3f s own  %7d calls  %s" % (r["cumulative_s"], r["total_s"], r["calls"], r["function"]))
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("DONE_PROFILE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
