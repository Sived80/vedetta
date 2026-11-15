"""The page reopens its live stream only when it is dead (#55): a resync keeps a healthy stream, and the ping of the server is an event the page sees.

Every reopen drops a stream while data flows, and the Home Assistant Supervisor logs each such drop as an error."""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "vedetta"))
from app.routes import ha as routes_ha  # noqa: E402

JS = os.path.join(ROOT, "vedetta", "app", "frontend", "ha", "js")


def read(name):
    with open(os.path.join(JS, name), encoding="utf-8") as f:
        return f.read()


# 1) the ping is a named event (a ":" comment never reaches EventSource, so the page could not tell a quiet stream from a dead one)
assert routes_ha.PING_FRAME.startswith("event: ping\n") and routes_ha.PING_FRAME.endswith("\n\n"), routes_ha.PING_FRAME
live = read("live.js")
assert 'on("ping"' in live, "the page must listen to the ping"

# 2) load() (called by roles, networks, return to the app, reopen after a drop) reconnects only through streamAlive()
body = live[live.index("export function load("):live.index("export function tick(")]
calls = re.findall(r"[^\n]*\bconnect\(\);", body)
assert calls and all("if (!streamAlive()) connect();" in c for c in calls), calls

# 3) the watchdog uses the stale time of the ping, not the time between two cycles
app = read("app.js")
assert "Date.now() - S.conn.last > STREAM_STALE_MS) connect();" in app
stale = int(re.search(r"STREAM_STALE_MS = (\d+);", read("core.js")).group(1))
assert stale >= 2 * routes_ha.PING_SECONDS * 1000 + 5000, stale   # two lost pings and some margin before calling it dead

print("TUTTO OK")
