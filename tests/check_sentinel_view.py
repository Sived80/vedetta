"""The Sentinel wired to the cycle (app/sentinel_view.py): a watched card that goes offline is announced once, after 5 minutes, and its
return after; a card not watched says nothing; the first state of a card is not a change; a new device goes to the senders; the
state is saved and read back after a restart; a sender that fails does not stop the others nor the cycle.
    python tests/check_sentinel_view.py"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import sentinel_view, state_support  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.sentinel import BACK, DOWN, NEW  # noqa: E402

CONFIG = {"nas": {"id": "nas", "watch": "1"}, "tv": {"id": "tv"}}
ha_data.config_map = lambda: CONFIG
alerts, sent = [], []


def alert(message, key, **params):
    alerts.append((key, params))


def broken_sender(events):
    raise RuntimeError("the network of the notifier is down")


sentinel_view.add_sender(broken_sender)
sentinel_view.add_sender(lambda events: sent.append([(e["kind"], e["card"]) for e in events]))


class History:
    def record_presence(self, *a):
        pass


async def scenario():
    presence = state_support.Presence(set())
    h = History()
    devices = {"nas": {"id": "nas", "name": "NAS", "ip": "10.0.0.5", "online": True}, "tv": {"id": "tv", "name": "TV", "ip": "10.0.0.6", "online": True}}
    # first states: not a change
    presence.record(h, devices["nas"], True, 0)
    presence.record(h, devices["tv"], True, 0)
    assert sentinel_view.sentinel().events == []
    # both go offline
    for c in ("nas", "tv"):
        devices[c]["online"] = False
        presence.record(h, devices[c], False, 100)
    assert sentinel_view.after_cycle(devices, alert, now=200) == [] and alerts == []
    ready = sentinel_view.after_cycle(devices, alert, now=400)                 # 300 s after: only the watched one
    assert [(e["kind"], e["card"]) for e in ready] == [(DOWN, "nas")]
    assert alerts == [("alert.device_down", {"label": "NAS", "ip": "10.0.0.5"})], alerts
    assert sent == [[(DOWN, "nas")]]
    # back
    devices["nas"]["online"] = True
    presence.record(h, devices["nas"], True, 1300)
    sentinel_view.after_cycle(devices, alert, now=1301)
    assert alerts[-1] == ("alert.device_back", {"label": "NAS", "ip": "10.0.0.5", "minutes": 20}), alerts[-1]
    # a new device: only to the senders (newdevicewatch has already announced it)
    sentinel_view.on_new_device("aa:bb:cc:dd:ee:ff", "Pixel", "10.0.0.9")
    n = len(alerts)
    sentinel_view.after_cycle(devices, alert, now=1400)
    assert len(alerts) == n and sent[-1] == [(NEW, "aa:bb:cc:dd:ee:ff")]


asyncio.run(scenario())

# saved, and read back after a restart
saved = json.loads(sentinel_view.STORE.read_text(encoding="utf-8"))
assert [e["kind"] for e in saved["events"]] == [DOWN, BACK, NEW], saved["events"]
sentinel_view._sentinel = None
assert [e["kind"] for e in sentinel_view.sentinel().events] == [DOWN, BACK, NEW]

# a "down" still waiting when its bell is switched off, or its card deleted: never sent
devices = {"nas": {"id": "nas", "name": "NAS", "ip": "10.0.0.5", "online": False}}
sentinel_view.on_presence(devices["nas"], False, 10000)
CONFIG["nas"] = {"id": "nas"}                                        # the bell switched off before the 5 minutes
assert sentinel_view.after_cycle(devices, alert, now=10400) == []
assert sentinel_view.sentinel().events[-1]["reason"] == "unwatched", sentinel_view.sentinel().events[-1]
CONFIG["nas"] = {"id": "nas", "watch": "1"}
sentinel_view.on_presence(devices["nas"], True, 20000)
sentinel_view.on_presence(devices["nas"], False, 30000)
del CONFIG["nas"]                                                    # the card deleted
assert sentinel_view.after_cycle(devices, alert, now=30400) == []
assert sentinel_view.sentinel().events[-1]["reason"] == "unwatched"

# a damaged state file: start empty, never an error for the cycle
sentinel_view._sentinel = None
sentinel_view.STORE.write_text("{oops", encoding="utf-8")
assert sentinel_view.sentinel().events == []
assert sentinel_view.after_cycle({}, alert, now=5000) == []
print("check_sentinel_view: ok")
