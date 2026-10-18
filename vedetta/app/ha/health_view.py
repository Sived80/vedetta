"""The network-health findings for the page and the log (health/). It reads the signals the app already has (the IP conflicts of the ARP scan), hands them to the judge now and then, and keeps the findings. Read-only: it sends nothing to any device.
Off unless VEDETTA_HEALTH=shadow is set. In shadow the findings are only counted in the log and kept for the export; nothing reaches the page, because a rule is shown only after it has been judged on real networks (see the promotion criteria of the project)."""
import asyncio
import contextlib
import os
import time

from ..applog import logger
from ..health import signals
from ..health.engine import Change, Engine
from ..recognition.identity import default_gateway
from ..scan import scanner
from ..storage import devices_config
from ..storage.history import history

REFRESH_S = 120
FIRST_AFTER_S = 600      # as for the analysis: right after a start the scan has not settled yet

_engine: Engine | None = None
_task: asyncio.Task | None = None
_on_change = None


def enabled() -> bool:
    return os.environ.get("VEDETTA_HEALTH", "").strip().lower() == "shadow"


SIGNAL_WINDOW_S = 86400      # the longest window a rule looks back (H05: one day)
LATENCY_WINDOW_S = 7 * 3600   # H07 looks at the last 15 minutes against the 6 hours before them


def gateway_latency(now: float, gateway=default_gateway, devices=devices_config.load_devices, points=history.latency_points) -> dict:
    """The latency of the gateway in the window of H07: the gateway is the device that has the address of the default route; without a route or without such a device there is nothing to judge."""
    ip = gateway()
    card = next((d for d in devices() if d.get("ip") == ip), None) if ip else None
    return {"gateway": points(card["id"], now - LATENCY_WINDOW_S, now)} if card else {}


def read_signals(now: float | None = None, presence=None, latency=None) -> dict:
    """What the rules look at: the IP conflicts of the scan, the drops of each device in the last day (from the presence history; the first sight of a device in the window is not a drop) and the latency of the gateway."""
    now = time.time() if now is None else now
    events = (presence or history.presence_since)(now - SIGNAL_WINDOW_S)
    return {"now": now, "conflicts": {ip: list(macs) for ip, macs in scanner.arp_conflicts.items()},
            "drops": signals.drops_by_device(events), "devices": len({device for device, _online, _ts in events}), "latency": (latency or gateway_latency)(now)}


def snapshot(engine: Engine | None = None) -> list[dict]:
    """The findings that the page may show: the active ones of the rules that are not in shadow. Counts only, no addresses."""
    engine = _engine if engine is None else engine
    if engine is None:
        return []
    return [{"rule": f.rule, "subject": f.subject, "severity": f.severity, "since": f.first_seen, "hits": f.hits}
            for f in engine.findings() if f.state == "active" and not f.shadow]


def summary(engine: Engine | None = None) -> dict:
    """What the export may tell about the judge, shadow included: how many findings, for which rule and in which state."""
    engine = _engine if engine is None else engine
    out: dict[str, dict[str, int]] = {}
    for f in (engine.findings() if engine else []):
        counts = out.setdefault(f.rule, {})
        counts[f.state] = counts.get(f.state, 0) + 1
    return out


def event() -> dict:
    return {"type": "health", "findings": snapshot()}


def _write(record, finding) -> None:
    record(rule=finding.rule, subject=finding.subject, state=finding.state, severity=finding.severity, first_seen=finding.first_seen, last_seen=finding.last_seen,
           hits=finding.hits, evidence=finding.evidence, shadow=finding.shadow)


def judge_once(engine: Engine, signals: dict, now: float, record=None) -> list[Change]:
    """One judgment; the changes of the rules that are shown are returned to the caller, the ones in shadow are only written in the log (counts). `record` (if given) writes every finding that is open
    and every one that has just ended, shadow included, so that a restart does not lose the record."""
    changes = engine.judge(signals, now)
    for c in changes:
        if c.finding.shadow:
            logger.info("Health (shadow): rule %s %s (%s)", c.finding.rule, c.change, c.finding.evidence)
    if record:
        for finding in {id(f): f for f in [*engine.findings(), *[c.finding for c in changes]]}.values():
            _write(record, finding)
    return [c for c in changes if not c.finding.shadow]


def _tick() -> bool:
    """One judgment of the real signals (and the write to disk); True if something the page shows has changed."""
    try:
        return bool(judge_once(_engine, read_signals(), time.time(), record=history.record_finding))
    except Exception:
        logger.exception("Judging the network health failed")
        return False


async def _loop() -> None:
    await asyncio.sleep(FIRST_AFTER_S)
    while True:
        if await asyncio.to_thread(_tick) and _on_change:
            _on_change(event())
        await asyncio.sleep(REFRESH_S)


def start(on_change=None) -> None:
    global _engine, _task, _on_change
    if not enabled():
        return
    _on_change = on_change
    _engine = _engine or Engine()
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
