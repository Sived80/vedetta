"""Verifica di isteresi, storico e confronto porte con dati simulati.
Si esegue nell'ambiente dell'app: python tests/check_phase_d.py
Usa un database temporaneo, non tocca config/vedetta.db."""
import asyncio
import tempfile
import time
from pathlib import Path

from app import state as state_mod
from app.history import History
from app.rescan import diff_ports

# ---- confronto porte ----
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

    # 1) primo controllo online
    st._apply(cfg, result(True), current)
    assert st.devices["d1"]["online"] is True and st.devices["d1"]["last_seen"] is None

    # 2) due controlli falliti: resta online (tolleranza), mac conservato
    st._apply(cfg, result(False), current)
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is True, "deve restare online entro la tolleranza"
    assert st.devices["d1"]["mac"] == "AA:BB", "i dati osservati non vanno persi"
    n_events = len([e for e in events if e["type"] == "device"])

    # 3) terzo fallimento: offline, con 'visto l'ultima volta'
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is False
    assert st.devices["d1"]["last_seen"] is not None
    assert len([e for e in events if e["type"] == "device"]) == n_events + 1

    # 4) torna online: azzera i fallimenti
    st._apply(cfg, result(True), current)
    assert st.devices["d1"]["online"] is True and st._misses["d1"] == 0

    # 5) un solo fallimento dopo il ritorno non lo fa cadere
    st._apply(cfg, result(False), current)
    assert st.devices["d1"]["online"] is True

    # storico: solo transizioni (online, offline, online) - nessun evento per i fallimenti tollerati
    await asyncio.sleep(0.3)
    rows = hist._db.execute("SELECT online FROM presence_events ORDER BY id").fetchall()
    assert [bool(r["online"]) for r in rows] == [True, False, True], [dict(r) for r in rows]
    print("ok: isteresi (3 controlli), last_seen, storico solo sulle transizioni")

    # 6) ripartenza: riprende lo stato dallo storico
    st2 = state_mod.DeviceState()
    await st2.load_history()
    assert st2._db_state["d1"] is True
    print("ok: ripartenza dallo storico")


asyncio.run(main())
print("TUTTO OK")
