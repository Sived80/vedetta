# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""«Add all» (1.0.4): the analysis of the devices before they are added (pipeline.start_associative) ran one device after the other, because every
device's pilot test (1000 ports) waited to be alone and its port scan then held a heavy slot, so the next pilot waited for it: about 23 s a device.
Now a few devices are analysed at once (pipeline.ASSOCIATIVE_PARALLEL), with the rules of the slow devices kept:
  - never more devices at once than the bound, never more port scans at once than the heavy slots of nmap;
  - a pilot may run beside other scans: "not slow" measured there is true (other scans only make a pilot slower), "slow" is never believed there:
    the pilot is run again alone, as before, and only that one decides (a healthy device measured slow under load keeps its scan of all ports);
  - under pressure of the host (host_load.busy) every pilot runs alone, as before;
  - one result per device, and the cancel of one address stops that one only, every permit given back.
nmap is a fake process (no packet leaves): it sleeps a little and answers like nmap; the semaphores and locks of scan_nmap are the real ones.
    python tests/check_add_all_parallel.py"""
import asyncio
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.scan import host_load, pipeline, scan_nmap  # noqa: E402
from app.scan.pipeline_plan import Batch  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


netutil.last_network = "192.0.2.0/24"
BOUND = getattr(pipeline, "ASSOCIATIVE_PARALLEL", 3)
HEAVY = scan_nmap._HEAVY_SLOTS
IPS = ["192.0.2.%d" % i for i in range(10, 22)]
SLOW = "192.0.2.12"           # answers slowly: slow alone too
VICTIM = "192.0.2.15"         # healthy, but its pilot looks slow when other scans run
PILOT_S, SCAN_S = 0.12, 0.35


async def fake_batch(profile, ips, steps=None):
    return Batch(steps=["ports_fast"])      # the port scan only: no broadcast, no web request


pipeline.prepare_batch = fake_batch

LOG = {"running": [], "peak_ips": 0, "peak_scans": 0, "pilots": [], "scans": {}}


def _xml(ip: str, elapsed: float) -> bytes:
    return ('<?xml version="1.0"?><nmaprun><host><status state="up"/><address addr="%s" addrtype="ipv4"/><ports/></host>'
            '<runstats><finished elapsed="%.1f"/></runstats></nmaprun>' % (ip, elapsed)).encode()


class FakeProc:
    def __init__(self, cmd):
        self.ip = cmd[-1]
        self.kind = "pilot" if "--top-ports" in cmd else "full" if "-p-" in cmd else "targeted" if scan_nmap.FAST_PORTS in cmd else "light"
        self.returncode = None

    async def communicate(self):
        running = LOG["running"]
        alone = self.kind == "pilot" and scan_nmap._NMAP_SEMAPHORE._value == 0 and not any(k != "light" for _, k in running)
        running.append((self.ip, self.kind))
        LOG["peak_ips"] = max(LOG["peak_ips"], len({ip for ip, _ in running}))
        LOG["peak_scans"] = max(LOG["peak_scans"], sum(1 for _, k in running if k in ("full", "targeted")))
        try:
            await asyncio.sleep({"pilot": PILOT_S, "full": SCAN_S, "targeted": SCAN_S}.get(self.kind, 0.01))
        finally:
            running.remove((self.ip, self.kind))
        elapsed = 0.5
        if self.ip == SLOW or (self.ip == VICTIM and not alone):
            elapsed = 9.0
        if self.kind == "pilot":
            LOG["pilots"].append((self.ip, alone))
        elif self.kind in ("full", "targeted"):
            LOG["scans"][self.ip] = self.kind
        self.returncode = 0
        return _xml(self.ip, elapsed), b""

    def kill(self):
        pass

    async def wait(self):
        return 0


class _Asyncio:
    """asyncio as scan_nmap sees it, with nmap a fake process."""
    def __getattr__(self, name):
        return getattr(asyncio, name)

    @staticmethod
    async def create_subprocess_exec(*cmd, **kw):
        return FakeProc(list(cmd))


scan_nmap.asyncio = _Asyncio()


def reset():
    LOG.update(running=[], peak_ips=0, peak_scans=0, pilots=[], scans={})


async def add_all(ips, cancel=None):
    reset()
    t0 = time.monotonic()
    tasks = pipeline.start_associative(ips, {})
    if cancel:
        await asyncio.sleep(0.05)
        pipeline.cancel_associative([cancel])
    got = await asyncio.gather(*tasks, return_exceptions=True)
    return got, time.monotonic() - t0


async def main():
    """One event loop for every case, like the app (the locks of scan_nmap belong to the loop that first waits on them)."""
    await all_together()
    await cancel_one()
    await under_pressure()


async def all_together():
    """1) twelve devices: several at once, within the bound, faster than one after the other."""
    host_load.busy = lambda reading=None: None      # a calm host: the real reading (Linux pressure files) would make it depend on the machine
    got, took = await add_all(IPS)
    serial = len(IPS) * (PILOT_S + SCAN_S)
    check(all(isinstance(r, dict) for r in got) and sorted(r["ip"] for r in got) == sorted(IPS), "one result per device")
    check(LOG["peak_ips"] > HEAVY, "more devices at once than port scans (a pilot beside them): %d at most" % LOG["peak_ips"])
    check(LOG["peak_ips"] <= BOUND, "never more than %d devices at once (%d)" % (BOUND, LOG["peak_ips"]))
    check(LOG["peak_scans"] <= HEAVY, "never more port scans at once than the heavy slots of nmap (%d)" % LOG["peak_scans"])
    check(took < 0.7 * serial, "faster than one after the other: %.2f s, one by one %.2f s" % (took, serial))
    check(LOG["scans"].get(SLOW) == "targeted", "the slow device keeps its targeted scan: %r" % LOG["scans"].get(SLOW))
    check(any(ip == SLOW and alone for ip, alone in LOG["pilots"]), "and slow was decided by a pilot alone: %r" % [p for p in LOG["pilots"] if p[0] == SLOW])
    check(LOG["scans"].get(VICTIM) == "full", "a healthy device that looked slow beside other scans keeps the scan of all ports: %r" % LOG["scans"].get(VICTIM))
    check(all(LOG["scans"].get(ip) == "full" for ip in IPS if ip != SLOW), "every healthy device gets the scan of all ports")
    check(scan_nmap._NMAP_SEMAPHORE._value == HEAVY and not scan_nmap._PILOT_LOCK.locked(), "every permit given back")


async def cancel_one():
    """2) the cancel of one address stops that one only."""
    got, _ = await add_all(IPS[:6], cancel=IPS[4])
    done = {r["ip"] for r in got if isinstance(r, dict)}
    check(done == set(IPS[:6]) - {IPS[4]}, "the cancelled address alone has no result: %r" % sorted(set(IPS[:6]) - done))
    check(scan_nmap._NMAP_SEMAPHORE._value == HEAVY and not scan_nmap._PILOT_LOCK.locked(), "every permit given back after a cancel")


async def under_pressure():
    """3) the host under pressure: every pilot alone, as before."""
    host_load.busy = lambda reading=None: "cpu"
    got, _ = await add_all(IPS[:5])
    check(all(isinstance(r, dict) for r in got), "under pressure: one result per device")
    check(LOG["pilots"] and all(alone for _, alone in LOG["pilots"]), "under pressure: every pilot alone: %r" % LOG["pilots"])


asyncio.run(main())
print("ALL OK" if not failed else "%d FAILED" % failed)
sys.exit(1 if failed else 0)
