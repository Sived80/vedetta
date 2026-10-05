"""Check of hysteresis, history and port comparison with simulated data.
Run in the app environment: python tests/check_phase_d.py
Uses a temporary database, does not touch config/vedetta.db."""
import asyncio
import tempfile
import time
from pathlib import Path

from app import state as state_mod
from app.history import History
from app.rescan import diff_ports

# ---- port comparison ----
old = [{"label": "80 · http"}, {"label": "22 · OpenSSH"}, {"label": "49200"}]
new = [{"label": "80 · http"}, {"label": "8883 · mqtt"}, {"label": "50000"}]
assert diff_ports(old, new) == ([8883], [22]), diff_ports(old, new)
assert diff_ports(None, new) == ([80, 8883], [])
print("ok: confronto porte (effimere ignorate)")


async def main():
    hist = History(Path(tempfile.mkdtemp()) / "t.db")
    state_mod.history = hist
    st = state_mod.DeviceState()
    alerts = []
    st.emit_alert = lambda m: alerts.append(m)

    def result(online, **extra):
        return {"id": "d1", "name": "Tel", "ip": "1.1.1.1", "port": 80, "url": "u", "online": online,
                "uptime": None, "mac": "AA:BB" if online else None, "vendor": None, "signal_kind": None,
                "signal_value": None, "signal_band": None, "signal_label": None, "signal_color": None,
                "extra": {}, "scanned_ports": [], "scanned_at": None, "is_mobile": False, **extra}

    cfg = {"id": "d1", "ip": "1.1.1.1"}
    current = {"d1": cfg}
    events = []
    st._emit = lambda e: events.append(e)
    st.render = lambda d: {"card": "c", "row": "r"}

    # 1) first check online
    st._apply(cfg, result(True), current)
    assert st.devices["d1"]["online"] is True and st.devices["d1"]["last_seen"] is None

    # 2) two failed checks: stays online (tolerance), mac kept
    st._apply(cfg, result(False), current)
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is True, "deve restare online entro la tolleranza"
    assert st.devices["d1"]["mac"] == "AA:BB", "i dati osservati non vanno persi"
    n_events = len([e for e in events if e["type"] == "device"])

    # 3) third failure: offline, with 'last seen'
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is False
    assert st.devices["d1"]["last_seen"] is not None
    assert len([e for e in events if e["type"] == "device"]) == n_events + 1

    # 4) comes back online: resets the failures
    st._apply(cfg, result(True), current)
    assert st.devices["d1"]["online"] is True and st._misses["d1"] == 0

    # 5) a single failure after the return does not make it drop
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is True

    # history: only transitions (online, offline, online) - no event for the tolerated failures
    await asyncio.sleep(0.3)
    rows = hist._db.execute("SELECT online FROM presence_events ORDER BY id").fetchall()
    assert [bool(r["online"]) for r in rows] == [True, False, True], [dict(r) for r in rows]
    print("ok: isteresi (3 controlli), last_seen, storico solo sulle transizioni")

    # 6) restart: resumes the state from the history
    st2 = state_mod.DeviceState()
    await st2.load_history()
    assert st2._db_state["d1"] is True
    print("ok: ripartenza dallo storico")


asyncio.run(main())
print("TUTTO OK")
