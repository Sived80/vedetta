"""The network-health findings for the page and the log (health/). It reads the signals the app already has (the IP conflicts of the ARP scan), hands them to the judge now and then, and keeps the findings. Read-only: it sends nothing to any device.
Off unless VEDETTA_HEALTH=shadow is set. In shadow the findings are only counted in the log and kept for the export; nothing reaches the page, because a rule is shown only after it has been judged on real networks (see the promotion criteria of the project)."""
import asyncio
import contextlib
import os
import time

from ..applog import logger
from ..health.engine import Change, Engine
from ..scan import scanner

REFRESH_S = 120
FIRST_AFTER_S = 600      # as for the analysis: right after a start the scan has not settled yet

_engine: Engine | None = None
_task: asyncio.Task | None = None
_on_change = None


def enabled() -> bool:
    return os.environ.get("VEDETTA_HEALTH", "").strip().lower() == "shadow"


def read_signals() -> dict:
    return {"conflicts": {ip: list(macs) for ip, macs in scanner.arp_conflicts.items()}}


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


def judge_once(engine: Engine, signals: dict, now: float) -> list[Change]:
    """One judgment; the changes of the rules that are shown are returned to the caller, the ones in shadow are only written in the log (counts)."""
    changes = engine.judge(signals, now)
    for c in changes:
        if c.finding.shadow:
            logger.info("Health (shadow): rule %s %s (%s)", c.finding.rule, c.change, c.finding.evidence)
    return [c for c in changes if not c.finding.shadow]


def _tick() -> None:
    """One judgment of the real signals; the page is told only if something it shows has changed."""
    try:
        shown = judge_once(_engine, read_signals(), time.time())
    except Exception:
        logger.exception("Judging the network health failed")
        return
    if shown and _on_change:
        _on_change(event())


async def _loop() -> None:
    await asyncio.sleep(FIRST_AFTER_S)
    while True:
        _tick()
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
