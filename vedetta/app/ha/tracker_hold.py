"""Presence held by Home Assistant (1.0.3). A phone asleep (Doze) stays on the Wi-Fi but does not answer ARP or ping for long stretches, while the
router still has it. When a MOBILE card does not answer in a check, the router trackers of Home Assistant (ha_trackers: source "router" only,
Vedetta's own MQTT trackers left out by their unique id) are asked about its MAC: "home" keeps it online, marked as held (state_cycle.settle);
"not_home" or another zone let the usual rule decide; "unavailable", "unknown", no tracker or no reading change nothing. A switch in the menu
(setting "phone_hold_ha", on by default) turns it off: then nothing is held and Home Assistant is not read.

Never a source: a GPS tracker (it says the person is in the home zone, not that the phone is on the network), a Bluetooth one (near a receiver,
not on the network), a card that is not mobile (a fixed device that does not answer is news, even if the router still lists it).

Read only, and light: Home Assistant is asked only in a check where a mobile card is silent, at most once every REFRESH_S; when the function
"devices seen by Home Assistant" is on, its own reading of every minute is used and nothing more is asked (unless it is older than STALE_S)."""
import asyncio
import time

from .. import i18n
from ..applog import logger
from ..storage import passive_store, settings
from . import ha_registry, ha_trackers

HELD = "ha"
REFRESH_S = 60
STALE_S = 180          # three readings of the passive function (one a minute) missed: its last one says nothing any more
_memo: dict = {"at": None, "home": {}}      # the last own reading (monotonic time) and what it said, MAC -> True/False/None


def forget() -> None:
    """The next check reads Home Assistant again (for the tests)."""
    _memo.update(at=None, home={})


def _silent_phone(result) -> bool:
    return isinstance(result, dict) and not result.get("online") and bool(result.get("is_mobile"))


def _mac(probe_input: dict, result: dict) -> str | None:
    """The card's MAC: its link, else the MAC its names were asked with, else the last one seen."""
    return ha_registry.norm_mac(probe_input.get("link") or result.get("mac_known") or probe_input.get("last_mac"))


async def mark(inputs: list[dict], results: list) -> None:
    """The silent mobile cards whose router tracker says "home" get `presence_held` in their result (in place); nothing else changes."""
    waiting = [k for k, (i, r) in enumerate(zip(inputs, results)) if _silent_phone(r) and _mac(i, r)]
    if not waiting or not ha_registry.token() or not settings.phone_hold_ha():      # the switch in the menu off: Home Assistant is not read at all
        return
    home = await _home_by_mac()
    for k in waiting:
        if home.get(_mac(inputs[k], results[k])) is True:
            results[k]["presence_held"] = HELD
            logger.debug("Presenza tenuta da Home Assistant: %s", inputs[k].get("ip"))


async def _home_by_mac() -> dict:
    if passive_store.enabled():
        data = await asyncio.to_thread(passive_store.snapshot)
        fresh = bool(data.get("read_at")) and time.time() - data["read_at"] <= STALE_S
        return {mac: row.get("online") for mac, row in data["candidates"].items()} if fresh else {}
    now = time.monotonic()
    if _memo["at"] is None or now - _memo["at"] >= REFRESH_S:
        _memo.update(at=now, home=await _read())
    return _memo["home"]


async def _read() -> dict:
    try:
        rows = await ha_trackers.fetch()
    except Exception as exc:   # Home Assistant down or no permission: nothing is held, the rule of today applies
        logger.debug("Tracker di Home Assistant non letti (%r)", exc)
        return {}
    return {row["mac"]: row["online"] for row in rows}


def attrs_for(device: dict) -> list[dict]:
    """The line of the device sheet that says the presence is held by Home Assistant, or nothing."""
    if device.get("presence_held") != HELD:
        return []
    return [{"key": "presence_held", "label": i18n.t("extra.presence_held"), "value": i18n.t("extra.presence_held_ha")}]
