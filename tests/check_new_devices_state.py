"""Reference (characterisation) test of DeviceState.check_new_devices, the part of the cycle that warns about never-seen MACs.

It pins down the behaviour of 0.6.2 without judging it, so that the cycle code can be moved with the proof that the result stays identical:
the first look is a silent baseline, a configured device (by IP or by MAC) is never "new", an unknown MAC raises one alert (not again in the
next cycle), alerts off means a log line only, the own IP and blocked devices are skipped, a failure of the check is swallowed, and the
event with the list of new devices is emitted only when the set of MACs changes."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod  # noqa: E402
from app.storage import blocklist, devices_config, newdevices, settings  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.scan import dhcp  # noqa: E402

H = History(Path(tempfile.mkdtemp()) / "vedetta.db")
_evaluate = newdevices.evaluate
newdevices.evaluate = lambda *a, **kw: _evaluate(*a, hist=H, **kw)        # the real logic, on a private database
newdevices.own_macs = lambda: set()
configs = [{"id": "d1", "ip": "10.0.0.5", "name": "Known"}]
devices_config.load_devices = lambda: list(configs)
settings.alerts_enabled = lambda: True
blocked = []
blocklist.matches = lambda mac=None, ip=None, name=None: mac in blocked
dhcp.seen.clear()

OWN = "10.0.0.2"
M_KNOWN, M_NEW, M_NEW2, M_BLOCK = ("aa:bb:cc:00:00:0%d" % i for i in (1, 2, 3, 4))


def arp(*pairs):
    return {ip: {"mac": mac, "vendor": None} for ip, mac in pairs}


def fresh_state():
    st = state_mod.DeviceState()
    st._new.own_ip = OWN
    st.alerts, st.events = [], asyncio.Queue()
    st.emit_alert = lambda message, key, **params: st.alerts.append((key, params["ip"], message))
    st._bus.subscribers.add(st.events)
    return st


def drain(st):
    out = []
    while not st.events.empty():
        out.append(st.events.get_nowait())
    return out


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def scenario():
    st = fresh_state()

    # --- 1) empty ARP: the baseline waits, nothing happens
    await st.check_new_devices({})
    assert st.alerts == [] and H.meta_get(newdevices.BASELINE_KEY) is None

    # --- 2) first look: everything seen is the baseline, no alert and no event
    await st.check_new_devices(arp(("10.0.0.5", M_KNOWN)))
    assert st.alerts == [] and H.meta_get(newdevices.BASELINE_KEY) is not None and drain(st) == []

    # --- 3) an unknown MAC: one alert with its IP, and the event with the list of the new ones
    a = arp(("10.0.0.5", M_KNOWN), ("10.0.0.9", M_NEW))
    await st.check_new_devices(a)
    assert [(k, ip) for k, ip, _ in st.alerts] == [("alert.new_device", "10.0.0.9")], st.alerts
    assert "MAC AA:BB:CC:00:00:02" in st.alerts[0][2]
    ev = drain(st)
    assert len(ev) == 1 and [d["mac"] for d in ev[0]["devices"]] == ["AA:BB:CC:00:00:02"], ev

    # --- 4) the next cycle with the same data: no second alert, no second event
    await st.check_new_devices(a)
    assert len(st.alerts) == 1 and drain(st) == []

    # --- 5) the own IP, a blocked device and a MAC that belongs to a configured IP are not new
    blocked.append(M_BLOCK.upper())
    await st.check_new_devices(arp(("10.0.0.5", M_KNOWN), ("10.0.0.9", M_NEW), (OWN, M_NEW2), ("10.0.0.30", M_BLOCK)))
    assert len(st.alerts) == 1 and not any(m == M_NEW2.upper() for m in H.known_all())

    # --- 6) alerts off: a new MAC is only logged (no alert), but the list still has it
    settings.alerts_enabled = lambda: False
    await st.check_new_devices(arp(("10.0.0.5", M_KNOWN), ("10.0.0.9", M_NEW), ("10.0.0.41", M_NEW2)))
    assert len(st.alerts) == 1
    macs = {d["mac"] for d in newdevices.list_new(H)}
    assert macs == {"AA:BB:CC:00:00:02", "AA:BB:CC:00:00:03"}, macs
    assert [len(e["devices"]) for e in drain(st)] == [2]

    # --- 7) a failure of the check is swallowed: nothing raised, the list is left as it was
    def boom(*a, **kw):
        raise RuntimeError("database gone")
    newdevices.evaluate = boom
    await st.check_new_devices(arp(("10.0.0.5", M_KNOWN)))
    assert drain(st) == []


run(scenario())
print("TUTTO OK")
