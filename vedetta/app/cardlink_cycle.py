"""The step of the cycle that keeps the card -> MAC links (1.0 step P4); the cycle reads them through linkview (step P5).

maclayer.record runs it after the verdict of the cycle (registered at start by main), at most every FULL_SWEEP_S. It gathers the facts the rule
needs (cardlink.judge: pure) and hands its answer to History.store_card_links, the one writer of card_mac:
  - the cards and their seq (devices.yaml), and the network of each address: the confirmed network that holds it, only if it is reached through
    the host's own interface and the address is on the line now (registry; K3: the network of a card is worked out from its address);
  - the verdict (macverdict) and the sessions of its window (the verdict's own 7 days);
  - the MACs of each card's presence history (History.card_macs);
  - for the cards whose history holds more than one MAC, the profile of each MAC as the notice of another device behind a card builds it
    (ha/identity_shift.profile) and whether it belongs to a network role, for the name check of the rule (L9).
The requests of step P5 (a link released when two cards of one phone are merged, the gesture "this is a new device") wait in linkview and are
written here, by the one writer, at the next judgement (cardlink.requested). After every judgement the rows just stored are read back into
linkview, and at start the rows of the last run (load). A failure is only logged: the cycle never sees it, and linkview keeps its last answer.
The export reads the counts (counts)."""
import time
from collections import Counter

from . import arpview, cardlink, linkview, macverdict, netutil
from .applog import logger
from .ha import identity_shift
from .networks import registry
from .recognition import roles, same_device
from .storage import devices_config, history as history_db
from .storage.history_maclayer import SEEDED_KEY

RECENT_DAYS = 7          # decision 3B (12/11): the card's history counts for the last week (the window of the verdict), plus the name check

_last = 0.0              # when the links were last judged (0: never in this run, so at the first cycle)
_unlinked: Counter = Counter()      # the reasons of the cards left without a link at the last judgement (counts for the export)


async def update(history, now: float | None = None) -> None:
    """One judgement of the links, at most every FULL_SWEEP_S; nothing while the main network has not been read yet. Never raises."""
    global _last
    now = time.time() if now is None else now
    if now - _last < arpview.FULL_SWEEP_S or not netutil.last_network:
        return
    _last = now
    try:
        _judge_and_store(history, now)
    except Exception:
        logger.exception("Legami fra schede e MAC non aggiornati")


def load(history) -> None:
    """At start: the links stored by the last run become the ones the cycle reads (linkview), before any judgement of this run. A failure is
    only logged."""
    try:
        linkview.load(history.card_links())
    except Exception:
        logger.exception("Legami fra schede e MAC non letti")


def _judge_and_store(history, now: float) -> None:
    cards = _cards(devices_config.load_devices(), netutil.last_network)
    asked = cardlink.requested(history.card_links(), linkview.requests(), cards, now)
    links = asked["links"]
    facts = _facts(history, cards, links, now)
    seeding = history.meta_get(SEEDED_KEY) is None
    res = cardlink.judge(cards, facts, links, now, seeding=seeding)
    write = list({r["device_id"]: r for r in asked["write"] + res["write"]}.values())
    delete = sorted(set(asked["delete"] + res["delete"]))
    if write or delete or seeding:
        history.store_card_links(write, delete, seeding)
    _unlinked.clear()
    _unlinked.update(res["unlinked"].values())
    stored = history.card_links()
    linkview.refresh(stored, now, offers=cardlink.offers(cards, stored, facts["sessions"], facts["kinds"], now), done=asked["done"])


def relink_offer(device_id: str) -> str | None:
    """The MAC the gesture "this is a new device" would link the card to, when the last judgement offered it (None otherwise)."""
    return linkview.offer(device_id)


def relink(device_id: str) -> bool:
    """The gesture: the card's link passes to the offered MAC at the next judgement, which comes at the next cycle; False when nothing is offered."""
    global _last
    mac = linkview.offer(device_id)
    if not mac:
        return False
    linkview.relink(device_id, mac)
    _last = 0.0
    return True


def _cards(devices: list[dict], cidr: str) -> list[dict]:
    """The cards as the rule takes them, each with the network of its address (None when it is not on the line of a direct network)."""
    nets = registry.direct_networks([d["ip"] for d in devices if d.get("ip")], cidr)
    return [{"id": d.get("id"), "seq": d.get("seq"), "ip": d.get("ip"), "name": d.get("name"), "name_mac": d.get("name_mac"),
             "network": nets.get(d.get("ip"))} for d in devices]


def _facts(history, cards: list[dict], links: dict, now: float) -> dict:
    sessions = [dict(s, mac=s["mac"].upper()) for s in history.sessions(now - RECENT_DAYS * 86400)]
    macs_of = history.card_macs(now - RECENT_DAYS * 86400)
    needed = {s["mac"] for s in sessions} | {r["mac"] for r in links.values()} | {m for h in macs_of.values() for m in h["older"]}
    profiles, role_macs = _profiles(history, [c for c in cards if len(macs_of.get(c["id"], {}).get("older", ())) > 1], sessions)
    return {"kinds": {m: k for m in needed if (k := macverdict.kind(m))}, "sessions": sessions, "history": macs_of, "profiles": profiles,
            "roles": role_macs}


def _profiles(history, cards: list[dict], sessions: list[dict]) -> tuple[dict, set]:
    """The profiles (identity_shift.profile) of the MACs behind the cards whose history holds more than one MAC, and of the MACs answering
    their addresses; the MACs whose address has a network role."""
    profiles, role_macs = {}, set()
    for c in cards:
        memory = {r["mac"].upper(): r for r in history.mac_memory_for(c["id"])}
        answering = {s["mac"] for s in sessions if s["ip"] == c["ip"]}
        for mac in set(memory) | answering:
            _profile_into(mac, memory.get(mac) or {"ip": c["ip"]}, profiles, role_macs)
    return profiles, role_macs


def _profile_into(mac: str, mem: dict, profiles: dict, role_macs: set) -> None:
    profiles[mac] = identity_shift.profile(mac.lower(), mem)
    if same_device.is_network(roles.roles_for(mem.get("ip"))):
        role_macs.add(mac)


def counts(history=None) -> dict | None:
    """Counts only, never a MAC or an address (for the export): links by state, held ones by reason, cards left without a link by reason (at the
    last judgement), links by source. None when the table cannot be read. `history`: the database of the service unless another is given."""
    history = history_db.history if history is None else history
    try:
        rows = history.card_links().values()
    except Exception:
        logger.exception("Conteggio dei legami fra schede e MAC non riuscito")
        return None
    return {"linked": sum(1 for r in rows if r["state"] == "linked"), "held": dict(Counter(r["reason"] for r in rows if r["state"] == "held")),
            "unlinked": dict(_unlinked), "source": dict(Counter(r["source"] for r in rows))}

