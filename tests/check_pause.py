"""Pausa del controllo periodico: scadenza, ripresa, aggiornamento a mano."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.state import DeviceState  # noqa: E402


async def go():
    s = DeviceState()
    polls = []

    async def fake_poll():
        polls.append(1)

    s.poll_once = fake_poll
    s._interval = lambda: 1  # type: ignore
    assert s.poll_info()["paused"] is False
    s.pause(0)
    info = s.poll_info()
    assert info["paused"] and info["paused_in_ms"] is None
    task = asyncio.create_task(s._loop())
    await asyncio.sleep(0.2)
    assert not polls, "in pausa non si controlla"
    s.trigger()
    await asyncio.sleep(0.2)
    assert not polls, "un trigger normale non rompe la pausa"
    s.trigger(force=True)
    await asyncio.sleep(0.2)
    assert len(polls) == 1, "l'aggiornamento a mano vale anche in pausa"
    await asyncio.sleep(1.3)
    assert len(polls) == 1, "la pausa continua dopo un aggiornamento a mano"
    s.resume()
    await asyncio.sleep(0.2)
    assert len(polls) == 2 and not s.poll_info()["paused"], "la ripresa controlla subito"
    s._paused_until = __import__("time").time() + 0.5  # pausa a tempo: riparte da sola
    n = len(polls)
    await asyncio.sleep(1.8)
    assert len(polls) > n and s.paused_remaining() is None, "scaduta la pausa si riparte"
    task.cancel()


asyncio.run(go())

# La pausa sopravvive al riavvio del servizio (file pause.json).
import json, pathlib, tempfile, time  # noqa: E402
from app import settings  # noqa: E402
settings.CONFIG_DIR = pathlib.Path(tempfile.mkdtemp())
a = DeviceState()
a.pause(0)
assert DeviceState().paused_remaining() == float("inf"), "senza scadenza dopo il riavvio"
a.pause(30)
assert 1700 < DeviceState().paused_remaining() <= 1800, "a tempo dopo il riavvio"
a.resume()
assert DeviceState().paused_remaining() is None and not (settings.CONFIG_DIR / "pause.json").exists()
(settings.CONFIG_DIR / "pause.json").write_text(json.dumps({"until": time.time() - 5}))
assert DeviceState().paused_remaining() is None, "una pausa scaduta non si riattiva"
print("TUTTO OK")
