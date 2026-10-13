"""The touch policy: how much a device is contacted. RULE: never risk commanding a device.
  none   - only watching (ARP, announcements, presence): the user chose «don't touch», or the device has a printing/industrial control port open and the user did not say otherwise;
  calm   - the device is slow (the all-ports pilot took 14-16 s): no risky step (all ports, service detection), nothing else changes;
  normal - everything the profile says.
The pre-analysis is this function: it reads only what the saved scan already knows (the slow flag, the open ports); it sends nothing."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state_cycle  # noqa: E402
from app.scan import pipeline, probe, rescan, rescan_background, touch_policy as tp  # noqa: E402
from app.scan.adapters import generic  # noqa: E402

PRINT = {"label": "9100 · jetdirect", "confirmed": False}
MODBUS = {"label": "502", "confirmed": False}
WEB = {"label": "80 · http", "confirmed": True}


def card(ports=(), slow=False, no_touch=None, ip="10.0.0.5"):
    info = {"ports": list(ports)}
    if slow:
        info["slow_scan"] = True
    return {"id": "d1", "ip": ip, "adapter": "generic", "port": 80, "scan_info": info, **({"no_touch": no_touch} if no_touch is not None else {})}


# the levels
assert tp.touch_level(card([WEB])) == tp.NORMAL and tp.touch_level({"ip": "x"}) == tp.NORMAL
assert tp.touch_level(card([WEB], slow=True)) == tp.CALM
assert tp.touch_level(card([PRINT])) == tp.NONE and tp.touch_level(card([MODBUS])) == tp.NONE          # automatic, from the open port
assert tp.touch_level(card([WEB], no_touch="on")) == tp.NONE and tp.touch_level(card([WEB], no_touch=True)) == tp.NONE   # the user's choice
assert tp.touch_level(card([PRINT], no_touch="off")) == tp.CALM          # the user took the automatic one away: still careful, not silent
assert tp.touch_level(card([WEB], no_touch="off")) == tp.NORMAL
assert tp.touch_level(card([PRINT], slow=True, no_touch="on")) == tp.NONE
assert tp.fragile_reasons(card([PRINT, WEB], slow=True)) == ["no_talk_port", "slow"] and tp.fragile_reasons(card([WEB])) == []
assert tp.may_touch(card([WEB])) and tp.may_touch(card([WEB], slow=True)) and not tp.may_touch(card([PRINT]))

# calm: only the risky steps go
steps = ["arp", "ha_registry", "mdns", "ports_fast", "ports_all", "service_os", "http_title", "tls_ssh", "igmp"]
kept = tp.calm_steps(steps)
assert kept == ["arp", "ha_registry", "mdns", "ports_fast", "http_title", "tls_ssh"], kept
assert tp.calm_batch(pipeline.Batch(steps=steps)).steps == kept

# 1) every cycle: a device that must not be touched gets no adapter call, its presence comes from ARP alone
called: list = []


async def stub_adapter(ip, port):
    called.append((ip, port))
    return {"online": True}


probe.ADAPTERS["generic"] = stub_adapter


async def one_cycle(device):
    arp = asyncio.get_running_loop().create_future()
    arp.set_result({device["ip"]: {"mac": "AA:BB:CC:00:00:01"}})
    return await probe._probe_device_gather(device, arp)


ip, port, result = asyncio.run(one_cycle(card([PRINT])))
assert not called and result["online"] is True, (called, result)           # online because ARP saw it
asyncio.run(one_cycle(card([WEB])))
assert called == [("10.0.0.5", 80)], called                                 # a normal device is asked as before

# 2) the response-time measure skips them too
targets = state_cycle.latency_targets([card([WEB], ip="10.0.0.1"), card([PRINT], ip="10.0.0.2"), card([WEB], ip="10.0.0.3", no_touch="on")])
assert [t[1] for t in targets] == ["10.0.0.1"], targets

# 3) the deep scan and the background scan of a device that must not be touched do not start; a calm one runs without the risky steps
ran: list = []


async def stub_run_deep(ip, batch, slow):
    ran.append((ip, list(batch.steps), slow))
    return {}


real_run_deep = pipeline.run_deep
pipeline.run_deep = stub_run_deep
try:
    assert asyncio.run(rescan.rescan_device(card([PRINT]), pipeline.Batch(steps=steps))) == {} and not ran
    asyncio.run(rescan.rescan_device(card([WEB], slow=True), pipeline.Batch(steps=steps)))
finally:
    pipeline.run_deep = real_run_deep
assert ran and ran[0][1] == kept and ran[0][2] is True, ran

started: list = []
real_task = asyncio.create_task


async def probe_schedule():
    rescan_background.schedule_full_ports(card([MODBUS]))
    return len(rescan_background._bg_tasks)


asyncio.run(probe_schedule())
assert "10.0.0.5" not in rescan_background._bg_tasks, "a background scan was scheduled for a device that must not be touched"

# 4) the plain connect of the adapter is not made to a no-talk port either (presence comes from ARP)
CONNECTED: list = []


async def fake_open_connection(host, port, **kw):
    CONNECTED.append(port)
    raise OSError("refused")


real = asyncio.open_connection
asyncio.open_connection = fake_open_connection
try:
    assert asyncio.run(generic._tcp_check("10.0.0.5", 9100)) is False and asyncio.run(generic._tcp_check("10.0.0.5", 502)) is False
    asyncio.run(generic._tcp_check("10.0.0.5", 80))
finally:
    asyncio.open_connection = real
assert CONNECTED == [80], CONNECTED
print("TUTTO OK")
