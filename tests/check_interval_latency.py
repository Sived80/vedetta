"""Check of the configurable check interval and response time.
Pure logic, no network: python tests/check_interval_latency.py (from the root
of the project). Uses a temporary database and settings file."""
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    import logging
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

from app.scan import latency
from app.storage import settings  # noqa: E402
from app.storage import history as history_mod  # noqa: E402

errors = 0


def check(cond, msg):
    global errors
    if not cond:
        print("ERRORE:", msg)
        errors += 1


tmp = Path(tempfile.mkdtemp())

# ---- settings: interval ----
settings.SETTINGS_PATH = tmp / "settings.json"
check(settings.poll_interval() == 30, "default 30 s")
for v in (10, 15, 30, 60, 120, 300):
    check(settings.update({"poll_interval": v})["poll_interval"] == v, f"valore ammesso {v}")
    check(settings.poll_interval() == v, f"riletto {v}")
for bad in (0, 5, 45, 301, "30", 30.0, True, None):
    try:
        settings.update({"poll_interval": bad})
        check(False, f"valore non valido accettato: {bad!r}")
    except ValueError:
        pass
check(settings.poll_interval() == 300, "valori non validi non cambiano nulla")
settings.update({"alerts": False})
check(settings.load() == {"alerts": False, "poll_interval": 300, "miss_limit": 3}, "alerts e intervallo coesistono")
settings.SETTINGS_PATH.write_text('{"poll_interval": 7, "alerts": true}', encoding="utf-8")
check(settings.poll_interval() == 30, "valore non valido nel file -> default")

# ---- stepwise rounding ----
q = latency.quantize
check(q(0.2) == 1 and q(0.7) == 1 and q(3.4) == 3 and q(9.6) == 10, "sotto 10 ms passo 1")
check(q(12) == 10 and q(13) == 15 and q(47) == 45 and q(49.9) == 50, "sotto 50 ms passo 5")
check(q(62) == 50 and q(63) == 75 and q(130) == 125, "oltre 50 ms passo 25")
check(q(None) is None and q(-1) is None, "senza dato")
check(latency.color(5) == "green" and latency.color(50) == "yellow" and latency.color(250) == "red", "colori")

# ---- moving average and per-minute sample ----
tr = latency.Tracker(window=3)
for ms in (10, 11, 12):
    tr.add("a", ms)
check(tr.value("a") == 10, "media 11 -> gradino 10")
tr.add("a", 14)  # window 11,12,14 = 12.3 -> 10
check(tr.value("a") == 10, "stabile con piccole variazioni")
for _ in range(3):
    tr.add("a", None)
check(tr.value("a") is None, "senza risposta la finestra si svuota")
tr.reset("a")

t0 = 1_000_000 * 60.0  # start of a minute
tr = latency.Tracker()
check(tr.take_minute(t0 + 1) == [], "primo giro: nessuna riga")
tr.add("a", 10)
tr.add("a", 20)
tr.add("b", 5)
check(tr.take_minute(t0 + 30) == [], "stesso minuto: nessuna riga")
rows = sorted(tr.take_minute(t0 + 61))
check(rows == [("a", t0, 15.0), ("b", t0, 5.0)], f"un campione medio per dispositivo: {rows}")
check(tr.take_minute(t0 + 62) == [], "dopo il flush si riparte da zero")

# ---- reduced series ----
since, until = 0.0, 86400.0
pts = [(i * 60.0, 10.0 + (i % 5)) for i in range(1440)]
red = latency.reduce_series(pts, since, until)
check(len(red["points"]) <= 120, f"al massimo 120 punti: {len(red['points'])}")
check(red["avg"] is not None and 10 <= red["avg"] <= 14 and red["max"] == 14.0, "media e massimo")
check(latency.reduce_series([], since, until)["points"] == [], "serie vuota")
few = latency.reduce_series([(100.0, 7.0), (5000.0, 9.0)], since, until)
check(len(few["points"]) == 2, "pochi punti restano separati")

# ---- history: table, a single transaction, pruning at 7 days ----
h = history_mod.History(tmp / "t.db")
now = time.time()
h.record_latency([("a", now - 60, 12.0), ("b", now - 60, 3.0), ("a", now - 8 * 86400, 99.0)])
check(len(h.latency_points("a", now - 9 * 86400, now)) == 2, "scrittura e lettura")
history_mod.time = time  # prune uses time.time()
h.prune()
left = h.latency_points("a", now - 9 * 86400, now)
check([m for _, m in left] == [12.0], f"potatura oltre 7 giorni: {left}")
check(len(h.latency_points("b", now - 3600, now)) == 1, "campioni recenti conservati")

print("OK" if not errors else f"{errors} errori")
sys.exit(1 if errors else 0)

# checks failed before offline
for v in settings.MISS_LIMITS:
    check(settings.update({"miss_limit": v})["miss_limit"] == v, f"miss_limit ammesso {v}")
for bad in (0, 4, True, "3", 11):
    try:
        settings.update({"miss_limit": bad})
        check(False, f"miss_limit {bad!r} doveva essere rifiutato")
    except ValueError:
        check(True, f"miss_limit {bad!r} rifiutato")
settings.update({"miss_limit": 3})
