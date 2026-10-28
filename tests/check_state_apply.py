"""Reference (characterisation) test of how the service decides whether a device is online or offline: DeviceState._apply.

It pins down the behaviour of 0.6.1 without judging it, so that the cycle code can be moved and split with the proof that the result stays
identical. It covers: the first presence, an identical cycle (no event), the tolerance to missed checks (the device stays online until the
limit is passed and keeps the data observed before), offline with the instant it was last seen, the return online, flapping faster than the
limit (never offline), a result that is stale against a changed configuration, the forced event, the remembered MAC (and the "shadow" work
only from online with a MAC), and the automatic name."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
H = History(tmp / "vedetta.db")
state_mod.history = H
named = []
named_macs = []      # the MAC behind the card when the name was found (kept as the origin of the name)
devices_config.update_auto_name = lambda device_id, name, source, force=False, mac=None: (named.append((device_id, name, source, force)), named_macs.append(mac))


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def mk(online, mac="aa:bb:cc:dd:ee:01", ip="10.0.0.5", **kw):
    r = {"id": "d1", "ip": ip, "online": online, "mac": mac, "name": "Prova", "vendor": "Acme", "brand": "Acme", "extra": dict(kw.pop("extra", {}))}
    r.update(kw)
    return r


CONFIG = {"id": "d1", "ip": "10.0.0.5", "name": "Prova"}
CURRENT = {"d1": CONFIG}


def fresh(limit=3):
    st = state_mod.DeviceState()
    st._miss_limit = lambda: limit
    st.shadow_calls = []
    st._shadow = lambda device_id, previous, result, now: st.shadow_calls.append((device_id, previous is not None, result.get("online")))
    q = asyncio.Queue()
    st._bus.subscribers.add(q)
    st.events = q
    return st


def drain(st):
    out = []
    while not st.events.empty():
        out.append(st.events.get_nowait())
    return out


async def settle(st):
    while st._bg:
        await asyncio.gather(*list(st._bg))


def presence(device_id="d1"):
    return [(bool(r[0]), round(r[1])) for r in H._db.execute("select online, ts from presence_events where device_id=? order by id", (device_id,)).fetchall()]


async def scenario():
    # --- 1) first presence: one card event, one presence row (online)
    st = fresh()
    st._apply(CONFIG, mk(True, extra={"k": 1}), CURRENT)
    await settle(st)
    assert st.devices["d1"]["online"] is True and st.rev == 1
    ev = drain(st)
    assert [e["type"] for e in ev] == ["device"] and ev[0]["id"] == "d1" and ev[0]["rev"] == 1
    assert presence() == [(True, presence()[0][1])] and len(presence()) == 1
    assert st._last_mac["d1"] == "aa:bb:cc:dd:ee:01" and st.shadow_calls == [("d1", False, True)]

    # --- 2) the same result again: nothing changes (no new revision, no event, no new presence row)
    st._apply(CONFIG, mk(True, extra={"k": 1}), CURRENT)
    await settle(st)
    assert st.rev == 1 and drain(st) == [] and len(presence()) == 1

    # --- 3) force: the event is sent even if the data are equal
    st._apply(CONFIG, mk(True, extra={"k": 1}), CURRENT, force=True)
    assert st.rev == 2 and [e["type"] for e in drain(st)] == ["device"]

    # --- 4) missed checks below the limit: still online, with the data observed before (the mac is kept), no offline row
    seen_at = st._last_seen["d1"]
    for i in (1, 2):
        st._apply(CONFIG, mk(False, mac=None, vendor=None, brand=None, extra={"x": i}), CURRENT)
        await settle(st)
        d = st.devices["d1"]
        assert d["online"] is True, i
        assert d["mac"] == "aa:bb:cc:dd:ee:01" and d["vendor"] == "Acme" and d["brand"] == "Acme", "the data observed before are kept"
        assert d["extra"] == {"k": 1, "x": i} and d["last_seen"] is None
        assert st._misses["d1"] == i and st._last_seen["d1"] == seen_at
    assert len(presence()) == 1, "no offline below the limit"

    # --- 5) the third missed check: offline, and the row carries the instant it was last seen online
    st._apply(CONFIG, mk(False, mac=None, vendor=None, brand=None), CURRENT)
    await settle(st)
    d = st.devices["d1"]
    assert d["online"] is False and d["last_seen"] == seen_at and d["latency_ms"] is None
    rows = presence()
    assert [r[0] for r in rows] == [True, False] and rows[1][1] == round(seen_at), rows
    assert any(e["type"] == "device" and e["device"]["online"] is False for e in drain(st))

    # --- 6) back online: the misses restart and a presence row is written
    st._apply(CONFIG, mk(True), CURRENT)
    await settle(st)
    assert st._misses["d1"] == 0 and st.devices["d1"]["online"] is True and st.devices["d1"]["last_seen"] is None
    assert [r[0] for r in presence()] == [True, False, True]
    return st


st = run(scenario())


async def flapping():
    """A phone that answers one check in two never goes offline with a limit of 3: the tolerance hides it (and so no event is written)."""
    s = fresh(limit=3)
    s._apply(CONFIG, mk(True), CURRENT)
    for _ in range(10):
        s._apply(CONFIG, mk(False), CURRENT)
        s._apply(CONFIG, mk(True), CURRENT)
    await settle(s)
    assert s.devices["d1"]["online"] is True
    return s


s2 = run(flapping())
assert [r[0] for r in presence("d1")][-1] is True

# --- start the history of the next scenarios from scratch
H._db.execute("delete from presence_events")
H._db.commit()


async def limits():
    # a limit of 1: the first missed check is already offline
    s = fresh(limit=1)
    s._apply(CONFIG, mk(True), CURRENT)
    s._apply(CONFIG, mk(False), CURRENT)
    await settle(s)
    assert s.devices["d1"]["online"] is False
    # a stale result (the configuration changed while the check was running) is ignored
    s = fresh()
    s._apply(CONFIG, mk(True), {"d1": {**CONFIG, "name": "Rinominato"}})
    assert s.devices == {} and s.rev == 0 and drain(s) == []
    # the automatic name goes to the configuration before the card is built
    named.clear()
    s = fresh()
    s._apply(CONFIG, mk(True, auto_name=("iPad-1", "dhcp")), CURRENT)
    s._apply({**CONFIG, "id": "d1"}, mk(True, auto_name=("iPad-2", "mdns", True)), CURRENT)
    assert named == [("d1", "iPad-1", "dhcp", False), ("d1", "iPad-2", "mdns", True)], named
    assert named_macs == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:01"], named_macs
    # an offline first result with a mac: the mac is remembered but the "shadow" work is only for online devices
    s = fresh()
    s._apply(CONFIG, mk(False, mac="aa:bb:cc:dd:ee:09"), CURRENT)
    await settle(s)
    assert s._last_mac["d1"] == "aa:bb:cc:dd:ee:09" and s.shadow_calls == []


run(limits())
print("TUTTO OK")
