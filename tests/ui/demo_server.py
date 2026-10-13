"""The REAL app (its routes, its templates, the modules of the page) on this machine, with four invented devices in its state and no scan, to look at the page in a browser or to let a test do it:
    python tests/ui/demo_server.py [port]        (then open http://127.0.0.1:<port>/ha)
Nothing is written outside a temporary folder and nothing is sent on the network."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
ROOT = Path(__file__).resolve().parents[2] / "vedetta"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import uvicorn  # noqa: E402
from fastapi import Response  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402

now = time.time()


def dev(i, name, **kw):
    d = {"id": f"d{i}", "name": name, "is_mobile": False, "ip": f"192.168.1.{i}", "port": 80, "url": f"http://192.168.1.{i}:80", "online": True, "uptime": 90000,
         "mac": f"AA:BB:CC:00:00:{i:02d}", "vendor": "TP-Link", "brand": "TP-Link", "signal_kind": "wifi", "signal_value": -55, "signal_band": "2.4 GHz", "signal_label": "good",
         "signal_color": "green", "extra": {"model": "X1"}, "scanned_ports": [{"label": "80 · http", "confirmed": True, "category": "web"}], "scanned_at": now - 5000, "last_seen": None}
    d.update(kw)
    return d


NAMES = ("Router casa", "Luce cucina", "Telefono", "Stampante studio")
for d in (dev(1, NAMES[0]), dev(2, NAMES[1], vendor="Shelly", brand="Shelly"), dev(3, NAMES[2], is_mobile=True, vendor="Apple", brand="Apple"),
          dev(4, NAMES[3], vendor="Brother", brand="Brother", scanned_ports=[{"label": "9100 · jetdirect", "confirmed": True, "category": "print"}])):
    state.devices[d["id"]] = d
state.ready.set()


@main.app.middleware("http")
async def no_event_stream(request, call_next):
    """The stream of events stays open for as long as the page lives: a browser started to look at the page (a test, a screenshot) would wait for it. Here it ends at once (204: the page does not ask again)."""
    if request.url.path.endswith("/api/ha/events"):
        return Response(status_code=204)
    return await call_next(request)


if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8790, lifespan="off", log_level="warning")
