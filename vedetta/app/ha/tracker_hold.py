# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Presence held by Home Assistant (1.0.3). A phone asleep (Doze) stays on the Wi-Fi but does not answer ARP or ping for long stretches, while the
router still has it. When a MOBILE card does not answer in a check, the router trackers of Home Assistant (ha_trackers: source "router" only,
Vedetta's own MQTT trackers left out by their unique id) are asked about its MAC: "home" keeps it online, marked as held (state_cycle.settle);
"not_home" or another zone let the usual rule decide; "unavailable", "unknown", no tracker or no reading change nothing.
A card with several MACs (1.0.4): a phone uses another private MAC on each Wi-Fi network, and the router tracker may know only the one of the main
network. So when the card's MAC of now is not "home", every PRIVATE MAC (locally administered: the per-network MACs of a phone) the presence
history saw behind the card counts too (one "home" holds it); never a maker's MAC (another device once at the address), and never
a MAC whose last event is behind another card or that is another card's MAC in this check (taken over), nor a MAC lent by a repeater or shared by
design (macverdict). Still the one reading of Home Assistant: the history is asked once for the MACs at home, not once per MAC. A switch in the menu
(setting "phone_hold_ha", on by default) turns it off: then nothing is held and Home Assistant is not read.

Never a source: a GPS tracker (it says the person is in the home zone, not that the phone is on the network), a Bluetooth one (near a receiver,
not on the network), a card that is not mobile (a fixed device that does not answer is news, even if the router still lists it).

Read only, and light: Home Assistant is asked only in a check where a mobile card is silent, at most once every REFRESH_S; when the function
"devices seen by Home Assistant" is on, its own reading of every minute is used and nothing more is asked (unless it is older than STALE_S)."""
import asyncio
import time

from .. import i18n, macverdict
from ..applog import logger
from ..storage import passive_store, settings
from ..storage.history import history
from . import ha_registry, ha_trackers

HELD = "ha"
REFRESH_S = 60
STALE_S = 180          # three readings of the passive function (one a minute) missed: its last one says nothing any more
_memo: dict = {"at": None, "home": {}}      # the last own reading (monotonic time) and what it said, MAC -> True/False/None
_owners: dict = {"at": None, "macs": frozenset(), "of": {}}    # the last answer of the history: the MACs at home -> the card each was seen behind


def forget() -> None:
    """The next check reads Home Assistant (and the history) again (for the tests)."""
    _memo.update(at=None, home={})
    _owners.update(at=None, macs=frozenset(), of={})


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
    rest = []
    for k in waiting:
        if home.get(_mac(inputs[k], results[k])) is True:
            _hold(inputs[k], results[k])
        else:
            rest.append(k)
    if rest:
        await _hold_by_other_macs(inputs, results, rest, home)


def _hold(probe_input: dict, result: dict) -> None:
    result["presence_held"] = HELD
    logger.debug("Presenza tenuta da Home Assistant: %s", probe_input.get("ip"))


async def _hold_by_other_macs(inputs: list[dict], results: list, rest: list[int], home: dict) -> None:
    """The silent phones left: held when a MAC at home (never a lent or shared one) was last seen behind that very card and is not another
    card's MAC in this check."""
    at_home = frozenset(m.upper() for m, on in home.items() if on is True and _private(m) and not macverdict.shared(m))
    if not at_home:
        return
    owner = await _owners_of(at_home)
    now_of = {}
    for i, r in zip(inputs, results):
        mac = _mac(i, r if isinstance(r, dict) else {})
        if mac:
            now_of.setdefault(mac.upper(), set()).add(i.get("id"))
    for k in rest:
        card = inputs[k].get("id")
        if any(owner.get(m) == card and now_of.get(m, {card}) == {card} for m in at_home):
            _hold(inputs[k], results[k])


def _private(mac: str) -> bool:
    """Locally administered (second hex digit 2, 6, A or E): a MAC made up by the device, as a phone does for each Wi-Fi network."""
    try:
        return bool(int(mac[:2], 16) & 2)
    except ValueError:
        return False


async def _owners_of(macs: frozenset) -> dict:
    """The history asked at most once every REFRESH_S for the same MACs at home (a phone away is silent at every check)."""
    now = time.monotonic()
    if _owners["at"] is None or now - _owners["at"] >= REFRESH_S or _owners["macs"] != macs:
        try:
            of = await asyncio.to_thread(history.mac_owners, sorted(macs))
        except Exception:      # the history cannot be read: only the MAC of now counts, as before 1.0.4
            logger.exception("Storico dei MAC delle schede non letto")
            of = {}
        _owners.update(at=now, macs=macs, of=of)
    return _owners["of"]


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
