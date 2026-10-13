"""Golden-master test of ha_tz.refresh (reads the time zone and the language from Home Assistant over a WebSocket, at most once an hour, five minutes after a failure): 4000 generated
runs with the collaborators replaced by deterministic in-memory ones - a frozen clock that moves 0.25 s at every call, a fake `websockets` module whose connection plays a script (the
greeting, the authentication, noise messages, the answer to get_config with a good, an unknown, an empty or a missing zone, a refused login, a bad JSON text, a connection that drops, a
refusal to connect, no module), a fake token, a fake `i18n` and a fake logger - must give exactly the return value, the final state (zone and time of the last attempt) and the ORDER of
every call (token, connect with its arguments, enter, receive, send with its text, language set, log with its arguments, exit, clock reads) stored in tests/golden/ha_tz_refresh.json,
written from the code as it was before the function was split.
Regenerate only on purpose:  HATZ_GOLDEN_UPDATE=1 python tests/check_ha_tz_refresh_golden.py"""
import asyncio
import json
import os
import random
import sys
import types
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_tz  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "ha_tz_refresh.json"
N = 4000
rng = random.Random(777)
C0 = 1_000_000.0
LOG: list = []
_clock = [C0]
SCRIPT: list = []
SETTINGS: dict = {}


def pick(seq):
    return seq[rng.randrange(len(seq))]


class FakeTime:
    @staticmethod
    def time():
        v = _clock[0]
        _clock[0] += 0.25
        LOG.append(["time"])
        return v


class FakeConn:
    async def __aenter__(self):
        LOG.append(["enter"])
        if SETTINGS["fail_enter"]:
            raise ConnectionRefusedError("no")
        return self

    async def __aexit__(self, *exc):
        LOG.append(["exit", exc[0].__name__ if exc[0] else None])
        return False

    async def recv(self):
        LOG.append(["recv"])
        if not SCRIPT:
            raise ConnectionError("closed")
        item = SCRIPT.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def send(self, text):
        LOG.append(["send", text])


def fake_connect(url, open_timeout=None):
    LOG.append(["connect", url, open_timeout])
    if SETTINGS["fail_connect"]:
        raise OSError("unreachable")
    return FakeConn()


class FakeLogger:
    @staticmethod
    def info(fmt, *args):
        LOG.append(["log", fmt, [str(a) for a in args]])


def fake_token():
    LOG.append(["token"])
    return SETTINGS["token"]


def fake_set_language(lang):
    LOG.append(["lang", lang])
    if SETTINGS["lang_fails"]:
        raise ValueError("bad language")


ha_tz.time = FakeTime
ha_tz.logger = FakeLogger
ha_tz.ha_registry = types.SimpleNamespace(token=fake_token, WS_URL="ws://fake/ws", TIMEOUT_S=7)
ha_tz.i18n = types.SimpleNamespace(set_system_language=fake_set_language)

ZONES = ["Europe/Rome", "UTC", "America/New_York", "Invalid/Zone", None, "", "Asia/Tokyo"]
LANGS = [None, "it", "en", ""]


def script():
    out = []
    r = rng.random()
    if r < 0.05:
        return out                                                       # nothing to receive: the connection drops at once
    if r < 0.6:                                                          # the usual conversation, with a good answer
        out = ['{"type": "auth_required"}', '{"type": "auth_ok"}'] + ['{"id": 2, "type": "result"}'] * rng.randrange(0, 2)
        out.append(json.dumps({"id": 1, "type": "result", "success": True, "result": {"time_zone": pick(ZONES[:3] + ["Asia/Tokyo", None, "Invalid/Zone"]), "language": pick(LANGS)}}))
        return out
    out.append(pick(['{"type": "auth_required"}'] * 12 + ['{"type": "other"}', "{}", "not json", "[]", '{"type": null}', ConnectionError("lost")]))
    if rng.random() < 0.9:
        out.append(pick(['{"type": "auth_ok"}'] * 12 + ['{"type": "auth_invalid"}', "{}", "nope", TimeoutError("slow")]))
    for _ in range(rng.randrange(0, 3)):
        out.append(pick(['{"id": 2, "type": "result"}', '{"type": "event"}', '{"id": 0}', '{"id": "1"}']))
    if rng.random() < 0.93:
        res = pick([{"time_zone": pick(ZONES), "language": pick(LANGS)}] * 6 + [{}, None, [], "x", {"language": "it"}])
        out.append(json.dumps({"id": 1, "type": "result", "success": pick([True] * 8 + [False, None, 0, 1]), "result": res}))
        if rng.random() < 0.1:
            out.append(json.dumps({"id": 1, "type": "result", "success": True, "result": {"time_zone": "Asia/Tokyo"}}))
    return out


def run_case():
    LOG.clear()
    _clock[0] = C0
    SCRIPT[:] = script()
    SETTINGS.update(token=pick(["tok"] * 12 + ["", None]), fail_connect=rng.random() < 0.03, fail_enter=rng.random() < 0.02, lang_fails=rng.random() < 0.02)
    sys.modules["websockets"] = None if rng.random() < 0.03 else types.SimpleNamespace(connect=fake_connect)
    ha_tz._state["zone"] = pick([None, None, ZoneInfo("Europe/Rome"), ZoneInfo("UTC")])
    ha_tz._state["at"] = pick([0.0, C0 - 3601, C0 - 3600, C0 - 7200] * 4 + [C0 - 3599.75, C0 - 3599.5, C0, C0 - 400, C0 - 100])
    force = rng.random() < 0.25
    try:
        r = loop.run_until_complete(ha_tz.refresh(force))
    except BaseException as exc:
        r = {"exception": type(exc).__name__}
    return [force, r, str(ha_tz._state["zone"]), ha_tz._state["at"], list(LOG)]


loop = asyncio.new_event_loop()
out = [run_case() for _ in range(N)]
loop.close()
sys.modules.pop("websockets", None)
out = json.loads(json.dumps(out))
if os.environ.get("HATZ_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert x == y, "case %d differs: %s" % (i, json.dumps([x, y])[:900])
assert not any(isinstance(o[1], dict) for o in out), [o for o in out if isinstance(o[1], dict)][:2]
rets = [o[1] for o in out]
assert sum(1 for r in rets if r is True) > 300 and sum(1 for r in rets if r is False) > 1500, "scenarios too uniform"
ev = [{e[0] for e in o[4]} for o in out]
assert sum(1 for e in ev if "lang" in e) > 1500 and sum(1 for e in ev if "log" in e) > 1000 and sum(1 for e in ev if "token" in e and "connect" not in e) > 200
assert sum(1 for o in out if any(e[0] == "log" and e[1].startswith("Fuso orario di") for e in o[4])) > 500, "no failures"
assert sum(1 for o in out if any(e[0] == "log" and e[1].startswith("Fuso orario:") for e in o[4])) > 300, "no changes"
assert sum(1 for o in out if not o[0] and o[4] == [["time"]]) > 300 and sum(1 for o in out if any(e[0] == "send" and "get_config" in e[1] for e in o[4])) > 1500
assert any(o[1] is False and any(e[0] == "lang" for e in o[4]) and not any(e[0] == "log" for e in o[4]) for o in out), "no unknown zone"
print("TUTTO OK")
