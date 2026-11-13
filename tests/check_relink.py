"""The gesture "this is a new device" (1.0 step P5, decision 2A of 12/11): a linked card whose device was replaced (a new printer at the same
address) stays offline for ever, because its link never moves to another MAC by itself. The gesture is offered only when it applies:
  the card is linked and offline, and for two judgements (10 minutes) exactly one other MAC - not lent, not virtual, of one device, not another
  card's link - answers its address while its own MAC does not (cardlink.offers, judged with the links, kept in linkview);
the request goes through the one writer (source "user"); the card keeps its id, name and history; refused when it does not apply. Its texts are
in every language of the app (en, it, de, cs)."""
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import cardlink, cardlink_cycle, linkview, maclayer, netutil  # noqa: E402
from app.routes import device_routes  # noqa: E402
from app.state import state  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.networks import registry as _routes  # noqa: E402
_routes.ROUTE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "no-route-file")   # the fake network, not the routes of this computer

NOW = 1_800_000_000.0
OLD, NEW, OTHER, REP = "02:00:00:00:80:01", "02:00:00:00:80:02", "02:00:00:00:80:03", "02:00:00:00:80:0A"
IP = "10.0.80.11"
KINDS = {OLD: "normal", NEW: "normal", OTHER: "private", REP: "lender"}


def row(device_id="printer", mac=OLD, state_="linked", network="main"):
    return {"device_id": device_id, "seq": 1, "network": network, "mac": mac, "state": state_, "reason": None, "source": "seed", "ip": IP,
            "since": NOW - 86400, "changed": NOW - 86400}


def arp(mac, start, end, ip=IP, source="arp"):
    return {"ip": ip, "mac": mac, "source": source, "start": start, "end": end}


CARD = [{"id": "printer", "seq": 1, "ip": IP, "network": "main"}]
OLD_GONE = [arp(OLD, NOW - 86400, NOW - 3600)]


def offers(sessions, links=None, kinds=KINDS, cards=CARD):
    return cardlink.offers(cards, {"printer": row()} if links is None else links, sessions, kinds, NOW)


# --- 1. when it is offered (pure)
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20)]) == {"printer": NEW}, "one other device, steady for 15 minutes, the old one gone"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20, source="arp_dup")]) == {"printer": NEW}
assert offers(OLD_GONE + [arp(NEW, NOW - 300, NOW - 20)]) == {}, "5 minutes: not yet (two judgements)"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 700)]) == {}, "it does not answer now"
assert offers([arp(OLD, NOW - 900, NOW - 20), arp(NEW, NOW - 900, NOW - 20)]) == {}, "the old device still answers"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20), arp(OTHER, NOW - 900, NOW - 20)]) == {}, "two other devices: which one?"
assert offers(OLD_GONE + [arp(REP, NOW - 900, NOW - 20)]) == {}, "a repeater answering for a client behind it is no device"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20)], kinds={OLD: "normal"}) == {}, "a MAC without verdict: not yet"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20), arp(REP, NOW - 900, NOW - 20)]) == {"printer": NEW}, "a lent MAC beside it is left out"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20)], links={"printer": row(state_="held")}) == {}, "a held link: not offered"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20)], links={"printer": row(), "laptop": row("laptop", NEW)},
              cards=CARD + [{"id": "laptop", "seq": 2, "ip": "10.0.80.12", "network": "main"}]) == {}, "the MAC is another card's link"
assert offers(OLD_GONE + [arp(NEW, NOW - 900, NOW - 20)], cards=[]) == {}, "the card is gone"
assert offers([arp(NEW, NOW - 900, NOW - 20, ip="10.0.80.99")] + OLD_GONE) == {}, "another address"

# --- 2. through the one writer and the route, on a database
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
netutil.last_network = "10.0.80.0/24"
cards_file = {"devices": [{"id": "printer", "ip": IP, "seq": 1, "name": "Office printer", "name_source": "user"}]}
devices_config.DEVICES_PATH.write_text(yaml.safe_dump(cards_file), encoding="utf-8")
H = History(tmp / "v.db")
now = time.time()
Obs = maclayer.Observation
for i in range(40):                                   # the old printer answered for 40 minutes, then the new one for the last 20
    t = now - 3600 + i * 60
    H.observe([Obs(IP, OLD, "arp", t)])
for i in range(21):
    t = now - 1200 + i * 60
    H.observe([Obs(IP, NEW, "arp", t)])
H.record_presence("printer", IP, OLD, True, now - 3600)
H.record_presence("printer", IP, OLD, False, now - 1200)
H.store_card_links([{**row(), "since": now - 7200, "changed": now - 7200}], [], True)
asyncio.new_event_loop().run_until_complete(maclayer.store_verdict(H, now=now))
cardlink_cycle._last = 0.0
asyncio.new_event_loop().run_until_complete(cardlink_cycle.update(H, now=now))
assert linkview.offer("printer") == NEW, linkview.offer("printer")
assert cardlink_cycle.relink_offer("printer") == NEW

app = FastAPI()
app.include_router(device_routes.router)
client = TestClient(app)
woken = []
state.trigger = lambda force=False, reason="": woken.append(reason)
state.devices["printer"] = {"id": "printer", "online": True, "name": "Office printer"}
assert client.get("/api/devices/printer/relink").json() == {"offer": False}, "online: nothing to offer"
assert client.post("/api/devices/printer/relink").status_code == 409 and not linkview.requests()
assert client.get("/api/devices/nope/relink").status_code == 404 and client.post("/api/devices/nope/relink").status_code == 404
state.devices["printer"]["online"] = False
assert client.get("/api/devices/printer/relink").json() == {"offer": True}
events_before = H._db.execute("SELECT COUNT(*) FROM presence_events WHERE device_id = 'printer'").fetchone()[0]
r = client.post("/api/devices/printer/relink")
assert r.status_code == 200 and r.json() == {"ok": True} and woken == ["relink"], (r.status_code, r.text, woken)
assert linkview.requests() == {"printer": ("relink", NEW)} and linkview.check("printer", 1, "main", now)[1] == "released"
asyncio.new_event_loop().run_until_complete(cardlink_cycle.update(H, now=now + 30))     # the next cycle judges at once
got = H.card_links()["printer"]
assert (got["mac"], got["state"], got["source"], got["seq"]) == (NEW, "linked", "user", 1), got
assert linkview.requests() == {} and linkview.offer("printer") is None, "written, and nothing more to offer"
card = devices_config.load_devices()[0]
assert (card["id"], card["name"], card["ip"]) == ("printer", "Office printer", IP), "id, name and address stay"
assert H._db.execute("SELECT COUNT(*) FROM presence_events WHERE device_id = 'printer'").fetchone()[0] == events_before, "the history stays"
assert client.post("/api/devices/printer/relink").status_code == 409, "nothing offered any more"

# --- 3. the texts, in every language of the app
LOC = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "locales"
KEYS = ("js.ha.relink.button", "js.ha.relink.hint", "js.ha.relink.done", "js.ha.relink.failed")
for lang in ("en", "it", "de", "cs"):
    texts = json.loads((LOC / lang / "ha.json").read_text(encoding="utf-8"))
    assert all((texts.get(k) or "").strip() for k in KEYS), (lang, [k for k in KEYS if not texts.get(k)])
JS = (Path(__file__).resolve().parent.parent / "vedetta" / "app" / "frontend" / "ha" / "js" / "more-attrs.js").read_text(encoding="utf-8")
assert "/relink" in JS and 'data-act="relink"' in JS, "the card offers the gesture"
print("TUTTO OK")
