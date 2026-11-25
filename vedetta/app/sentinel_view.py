"""The Sentinel at work (the rules are in sentinel.py): it is told what changed by the cycle (a card online/offline, a new device),
and at the end of each cycle it sends what is ready. Its state is saved in sentinel.json, so a "down" sent before a restart still
gives its "back" after.

Who is watched for "down": the cards with the choice "tell me if it disappears" (the override "watch" of devices.yaml). Who may
sleep: a phone or a tablet (is_mobile). The messages go to the log, the journal and the open pages (emit_alert) and to the senders
registered with add_sender (step 3: outside the browser). A new device is already announced by newdevicewatch: here it only goes
to the senders."""
import json
import time
from collections.abc import Callable

from . import paths
from .applog import logger
from .atomic import write_atomic
from .ha import ha_data, ha_notify
from .sentinel import BACK, DOWN, Sentinel

STORE = paths.data_path("sentinel.json")
_sentinel: Sentinel | None = None
_saved = ""                                     # the JSON last written, to write only when something changed
_senders: list[Callable[[list[dict]], None]] = []


def sentinel() -> Sentinel:
    global _sentinel, _saved
    if _sentinel is None:
        try:
            text = STORE.read_text(encoding="utf-8")
            _sentinel, _saved = Sentinel.from_json(json.loads(text)), text
        except (OSError, ValueError):
            _sentinel = Sentinel()
    return _sentinel


def add_sender(send: Callable[[list[dict]], None]) -> None:
    """A way out of the browser (step 3): called once per cycle with the events sent, never with an empty list."""
    _senders.append(send)


def watched(card_id: str) -> bool:
    return bool((ha_data.config_map().get(card_id) or {}).get("watch"))


def on_presence(result: dict, online: bool, ts: float) -> None:
    """A card changed between online and offline (state_support.Presence: only real changes, after the tolerance to missed checks)."""
    try:
        sentinel().presence(result["id"], online, ts, watched=watched(result["id"]), label=result.get("name") or result.get("ip") or result["id"],
                            ip=result.get("ip") or "-", **ha_data.device_facts(result, ha_data.config_map().get(result["id"])))
    except Exception:
        logger.exception("Sentinella: cambio di presenza non registrato")


def on_new_device(mac: str, label: str, ip: str, entry: dict | None = None) -> None:
    """A new device (entry: its row of the watch, newdevices: MAC, address, host name, maker, brand; "network" when it lives behind the
    router): its facts and why it is new go with the event, taken from what the watch already has."""
    try:
        sentinel().new_device(mac, time.time(), label=label, ip=ip, **_new_facts(entry or {}))
    except Exception:
        logger.exception("Sentinella: nuovo dispositivo non registrato")


def _new_facts(entry: dict) -> dict:
    """The facts of a new device, from its row of the watch (it has no card yet: no choice made by hand), and why it is new."""
    device = {"id": entry.get("mac") or entry.get("ip"), "mac": entry.get("mac"), "ip": entry.get("ip"), "name": entry.get("hostname"),
              "vendor": entry.get("vendor"), "vendor_role": entry.get("vendor_role"), "brand": entry.get("brand")}
    reason = ha_notify.NEW_BEHIND_ROUTER if entry.get("network") else ha_notify.NEW_MAC
    return {**ha_data.device_facts(device), "reason": reason}


def after_cycle(devices: dict, emit_alert: Callable[..., None], now: float | None = None) -> list[dict]:
    """End of a cycle: what is ready goes out, once; the state is saved if it changed. Never raises: the cycle must go on."""
    now = time.time() if now is None else now
    try:
        s = sentinel()
        s.forget_gone(set(devices), now)
        ready = s.due(now, lambda c: not (devices.get(c) or {}).get("online", False), lambda c: bool((devices.get(c) or {}).get("is_mobile")),
                      watched)
        s.mark_sent(ready, now)
        _announce(ready, emit_alert)
        _deliver(ready)
        s.prune(now)
        _save(s)
        return ready
    except Exception:
        logger.exception("Sentinella: fine ciclo non riuscita")
        return []


def _announce(ready: list[dict], emit_alert) -> None:
    for ev in ready:
        p = ev.get("params") or {}
        if ev["kind"] == DOWN:
            emit_alert(f"Non risponde: {p.get('label')} ({p.get('ip')})", "alert.device_down", label=p.get("label"), ip=p.get("ip"))
        elif ev["kind"] == BACK:
            minutes = max(1, round((p.get("away_s") or 0) / 60))
            emit_alert(f"Di nuovo in rete: {p.get('label')} ({p.get('ip')}) dopo {minutes} min", "alert.device_back",
                       label=p.get("label"), ip=p.get("ip"), minutes=minutes)
        # NEW: newdevicewatch has already announced it


def _deliver(ready: list[dict]) -> None:
    if not ready:
        return
    for send in _senders:
        try:
            send(ready)
        except Exception:
            logger.exception("Sentinella: invio non riuscito")


def _save(s: Sentinel) -> None:
    global _saved
    text = json.dumps(s.to_json(), separators=(",", ":"), sort_keys=True)
    if text == _saved:
        return
    try:
        write_atomic(STORE, lambda f: f.write(text), ".sentinel-", durable=False)
        _saved = text
    except OSError:
        logger.exception("Sentinella: stato non salvato")

