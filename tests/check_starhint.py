"""The one-time invitation to star the project: it needs a few days of history, comes only once (the memory is on the server and survives a
restart), an old installation sees it once after the update, and the app option switches it off."""
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import paths  # noqa: E402
from app.storage import starhint  # noqa: E402
from app.storage import history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.routes import ha as routes_ha  # noqa: E402

tmp = Path(tempfile.mkdtemp())
starhint.CONFIG_DIR = tmp
starhint.STAR_PATH = tmp / "star_hint.json"
os.environ.pop("VEDETTA_STAR_HINT", None)
now = time.time()
DAY = 86400

# the rule: no history, too young, old enough
starhint._done = None
assert not starhint.should_show(None, now), "senza storia non compare"
assert not starhint.should_show(now - 2 * DAY, now), "troppo giovane: non compare"
assert starhint.should_show(now - 4 * DAY, now), "con qualche giorno di storia compare (anche una installazione vecchia)"
assert starhint.should_show(now - 400 * DAY, now), "una installazione vecchia la vede dopo l'aggiornamento"

os.environ["VEDETTA_STAR_MIN_AGE_DAYS"] = "0"
assert starhint.should_show(now - 5, now), "la copia di debug non aspetta"
os.environ.pop("VEDETTA_STAR_MIN_AGE_DAYS")

# the option switches it off
os.environ["VEDETTA_STAR_HINT"] = "false"
assert not starhint.enabled() and not starhint.should_show(now - 9 * DAY, now), "l'opzione la spegne"
os.environ["VEDETTA_STAR_HINT"] = "true"
assert starhint.enabled()
os.environ.pop("VEDETTA_STAR_HINT")

# once: after mark_done it never comes back, also after a restart (the module forgets, the file remembers)
starhint.mark_done()
assert starhint.done() and not starhint.should_show(now - 9 * DAY, now)
starhint._done = None
assert starhint.done() and not starhint.should_show(now - 9 * DAY, now), "dopo un riavvio non torna"
assert starhint.STAR_PATH.exists()

# over HTTP: the summary says when it may appear, the POST closes it for good
starhint._done = None
starhint.STAR_PATH.unlink()
H = History(tmp / "vedetta.db")
history_mod.history = H
routes_ha.history = H
routes_ha._first_ts = None
app = FastAPI()
app.include_router(routes_ha.router)
c = TestClient(app)
assert H.first_event_ts() is None
assert routes_ha.asyncio.run(routes_ha._star_hint()) is False, "senza storia il riepilogo non la propone"
H._db.execute("INSERT INTO presence_events (device_id, ip, mac, online, ts) VALUES ('d1', '192.168.1.5', 'aa', 1, ?)", (now - 5 * DAY,))
H._db.commit()
routes_ha._first_ts = None
assert routes_ha.asyncio.run(routes_ha._star_hint()) is True, "con 5 giorni di storia il riepilogo la propone"
r = c.post("/api/ha/star")
assert r.status_code == 200 and r.json() == {"ok": True}
assert routes_ha.asyncio.run(routes_ha._star_hint()) is False, "dopo il POST non viene piu' proposta"
starhint._done = None
assert routes_ha.asyncio.run(routes_ha._star_hint()) is False, "nemmeno dopo un riavvio"

print("TUTTO OK")
