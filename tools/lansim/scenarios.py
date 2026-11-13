"""The scenarios: what happens to the cards of Vedetta when the virtual phones do the things that produce doubles or wrong names. Each scenario builds its own
network and a fresh Vedetta, drives the phones, and returns what the cards say; the expectations are in the docstrings and judged by run_scenarios.py."""
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.lansim import phases
from tools.lansim.lan import EXTENDER2_MAC, EXTENDER_MAC, ROUTER_MAC, SUBNET, Lan, _ns
from tools.lansim.vedetta_proc import VedettaProcess

ANDROID_MAC, IOS_MAC, IOS_MAC_2 = "c6:00:00:00:00:21", "5a:00:00:00:00:22", "5a:00:00:00:00:24"
SETTLE = 2         # update cycles to wait after a change before looking at the cards


def _phone_cards(vedetta: VedettaProcess) -> list[dict]:
    return sorted(({"ip": c.get("ip"), "name": c.get("name"), "name_source": c.get("name_source"), "online": c.get("online"),
                    "brand": c.get("brand"), "type": c.get("type")} for c in vedetta.cards() if c.get("is_mobile") or c.get("type") == "phone"),
                  key=lambda c: c["ip"] or "")


def _ip_conflict_rows(vedetta: VedettaProcess) -> int:
    """How many contested addresses the single MAC verdict of this run stored (ip_conflict): none is expected where a repeater lends its MAC or a device
    takes the address of another (1.0 step P3: these rows now raise H20)."""
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(vedetta.data, "vedetta.db"), uri=True)
    try:
        return db.execute("SELECT COUNT(*) FROM ip_conflict").fetchone()[0]
    finally:
        db.close()


# The card -> MAC link (1.0 step P4): what card_mac says at the end of a run, against the truth the scenario knows. Since step P5 the app uses a link only when it may be
# trusted (linkview, U1-U6): "wrong" counts the usable links only, with the same constants as the app (tests/check_lansim_pure.py); the links stored but not usable yet are
# counted apart (wrong_stored), so that nothing is hidden.
NEVER = (EXTENDER_MAC, EXTENDER2_MAC)      # where the extenders lend their MAC (S4, S10): no card may be linked to it, not even the extender's own
LINK_WAIT_S = 720                          # a link needs two full sweeps of answers and a judgement (every five minutes): about ten minutes from the start
STABLE_S = 600                             # linkview.STABLE_S: a link is used once it has been stable for two judgements
HOLD_KINDS = ("lender", "virtual", "multi_address", "conflict")      # linkview.HOLD_KINDS: the verdict of these MACs stops a link from being used
USABLE_WAIT_S = LINK_WAIT_S + STABLE_S + 120     # a link born, then stable for two judgements, then read by a cycle


def usable_ids(links: dict, seqs: dict, kinds: dict, now: float) -> set:
    """The cards whose stored link the app may use now (U1-U4, U6 of linkview; U5 holds in a run that judges every five minutes): linked, the seq of the card, stable for
    STABLE_S, its MAC not lent, virtual, on two addresses or in a conflict in the verdict (mac_class). links: device id -> (mac, state, seq, changed)."""
    return {d for d, (mac, state, seq, changed) in links.items()
            if state == "linked" and seqs.get(d) == seq and now - changed >= STABLE_S and kinds.get(mac.upper()) not in HOLD_KINDS}


def link_tally(links: dict, truth: dict, never=(), usable=None) -> dict:
    """links: device id -> (mac, state, seq[, changed]) as card_mac holds them; truth: device id -> the MAC of the device at its address when the cards were added. Counts right,
    wrong (another MAC, or a MAC of `never`), absent, held, and the MACs linked to two cards; `by_card` gives the verdict of each card of the truth. `usable`: the cards whose
    link the app may use (usable_ids); then "wrong" counts those only and "wrong_stored" every stored link (without it, both count every stored link)."""
    never = {m.lower() for m in never}
    by_card = {d: _link_verdict(links.get(d), want.lower(), never) for d, want in truth.items()}
    out = {k: list(by_card.values()).count(k) for k in ("right", "wrong", "absent", "held")}
    out["wrong"] += _wrong_elsewhere(links, truth, never)
    out["wrong_stored"] = out["wrong"]
    if usable is not None:
        out["wrong"] = sum(1 for d, v in by_card.items() if v == "wrong" and d in usable) + _wrong_elsewhere({d: r for d, r in links.items() if d in usable}, truth, never)
    out["two_cards"] = _two_cards(links)
    out["by_card"] = by_card
    return out


def _wrong_elsewhere(links: dict, truth: dict, never: set) -> int:
    """Links of cards outside the truth to a MAC that no card may have (an extender's)."""
    return sum(1 for d, link in links.items() if d not in truth and link[0].lower() in never)


def _two_cards(links: dict) -> int:
    macs = [link[0].lower() for link in links.values()]
    return sum(1 for m in set(macs) if macs.count(m) > 1)


def _link_verdict(link, want: str, never: set) -> str:
    if link is None:
        return "absent"
    mac, state = link[0].lower(), link[1]
    if mac != want or mac in never:
        return "wrong"
    return "held" if state == "held" else "right"


def _card_links(vedetta: VedettaProcess) -> dict:
    """The rows of card_mac, read-only: device id -> (mac, state, seq, changed); none when the table is not there (an older version)."""
    return _read_db(vedetta.data, "SELECT device_id, mac, state, seq, changed FROM card_mac", lambda rows: {d: (m, s, q, c) for d, m, s, q, c in rows})


def _read_db(data: str, sql: str, shape, empty=None):
    """One read-only query on the database of a run, shaped by `shape(rows)`; `empty` (else {}) when the table is not there (an older version)."""
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(data, "vedetta.db"), uri=True)
    try:
        return shape(db.execute(sql).fetchall())
    except sqlite3.OperationalError:
        return {} if empty is None else empty
    finally:
        db.close()


def _kinds(vedetta: VedettaProcess) -> dict:
    """The verdict stored by the run (mac_class): MAC (upper case) -> kind."""
    return _read_db(vedetta.data, "SELECT mac, kind FROM mac_class", lambda rows: {m.upper(): k for m, k in rows})


def online_share(events: list[tuple], since: float, now: float) -> float:
    """The share of [since, now] a card was online, from its presence events (ts, online), in order; offline before the first one."""
    total, state, last = 0.0, False, since
    for ts, online in events:
        ts = max(ts, since)
        if state:
            total += ts - last
        state, last = bool(online), ts
    if state:
        total += now - last
    return round(total / (now - since), 3) if now > since else 0.0


def _online_shares(vedetta: VedettaProcess, addresses: list[str], since: float) -> dict:
    """Address -> the share of the run the card at that address was online (the phones behind the extenders, P5: not lower than with P4)."""
    ids = {c["id"]: c["ip"] for c in vedetta.cards() if c.get("ip") in addresses}
    events = _read_db(vedetta.data, "SELECT device_id, ts, online FROM presence_events ORDER BY ts, id", lambda rows: rows, empty=[])
    now = time.time()
    return {ip: online_share([(ts, on) for d, ts, on in events if d == card], since, now) for card, ip in sorted(ids.items(), key=lambda x: x[1])}


def _base_macs(extenders: int = 1) -> dict:
    """The MAC at each address of the fixed machines of the LAN (the router and the extenders)."""
    out = {SUBNET + ".1": ROUTER_MAC, SUBNET + ".3": EXTENDER_MAC}
    if extenders > 1:
        out[SUBNET + ".4"] = EXTENDER2_MAC
    return out


def _truth(vedetta: VedettaProcess, macs_by_ip: dict) -> dict:
    """Device id -> the MAC of the device at its address now (to be taken right after the cards are added)."""
    return {c["id"]: macs_by_ip[c["ip"]] for c in vedetta.cards() if c.get("ip") in macs_by_ip}


def _links(vedetta: VedettaProcess, truth: dict, never=()) -> dict:
    """The tally of the links of this run, "wrong" over the links the app may use. Where an extender never lends its MAC (it holds no client) it is a device like any other: its
    own card may be linked to it."""
    links = _card_links(vedetta)
    return link_tally(links, truth, never, usable=usable_ids(links, _seqs(vedetta.data), _kinds(vedetta), time.time()))


def _wait_usable(vedetta: VedettaProcess, device_id: str | None, timeout: float) -> bool:
    """Waits until the card's link may be used by the app (linked, stable for STABLE_S, then one cycle more), at most `timeout` seconds."""
    end = time.time() + timeout
    while time.time() < end:
        row = _card_links(vedetta).get(device_id) if device_id else None
        if row and row[1] == "linked" and time.time() - row[3] >= STABLE_S + 30:
            return True
        time.sleep(20)
    return False


def _wait_link(vedetta: VedettaProcess, device_id: str | None, timeout: float) -> bool:
    """Waits until the card is linked (at most `timeout` seconds)."""
    end = time.time() + timeout
    while time.time() < end:
        if device_id and (_card_links(vedetta).get(device_id) or ("", ""))[1] == "linked":
            return True
        time.sleep(20)
    return False


def _id_at(vedetta: VedettaProcess, address: str) -> str | None:
    return next((c["id"] for c in vedetta.cards() if c.get("ip") == address), None)


def s1_stable(code_dir: str) -> dict:
    """An Android phone on the network, nothing happens: one phone card, named as the phone announces itself; its card ends linked to the phone's MAC (P4)."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: ANDROID_MAC})
        vedetta.wait_cycles(SETTLE + 1)
        phones = _phone_cards(vedetta)
        phone_id = _id_at(vedetta, address)
        _wait_link(vedetta, phone_id, LINK_WAIT_S)
        links = _links(vedetta, truth)
        return {"phones": phones, "links": links, "phone_link": links["by_card"].get(phone_id, "absent")}


def s4_extender_holds(code_dir: str) -> dict:
    """The extender answers for the phone's address in turns with the phone, several times: still one phone card, the same name, no new card for the extender's MAC."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        started = time.time()
        truth = _truth(vedetta, {**_base_macs(), address: ANDROID_MAC})
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        for held in (True, False, True, False, True, False):
            lan.hold("c1", address, "ext" if held else None)
            vedetta.wait_cycles(1)
        vedetta.wait_cycles(SETTLE)
        after = _phone_cards(vedetta)
        _wait_link(vedetta, _id_at(vedetta, address), 300)          # linked to the phone, or not linked: never to the extender
        return {"before": before, "after": after, "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta), "links": _links(vedetta, truth, NEVER),
                "online_share": _online_shares(vedetta, [address], started)}


def s5_inherited_name(code_dir: str) -> dict:
    """An Android phone leaves; an iPhone with a private MAC takes the same address. The card must not carry on with the Android name."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: ANDROID_MAC})
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", IOS_MAC, 20)
        lan.announce("c2", "ios", IOS_MAC, address)
        vedetta.wait_cycles(SETTLE + 2)
        return {"before": before, "after": _phone_cards(vedetta), "links": _links(vedetta, truth)}


def s10_two_extenders(code_dir: str, cycles: int = 24, seed: int = 1, dense: bool = False) -> dict:
    """Three phones walk around a house with two extenders and the router's own Wi-Fi in the middle (extender 1 - router - extender 2, the extenders far from each other, at the same distance from
    the router): they are held now by one extender, now by the other, now by nobody (on the router's Wi-Fi). Still one card per phone, the same names, no card for the extenders' MACs on the
    phones' addresses, and the cards of the two extenders keep their own addresses. `dense`: very short stretches and more direct hand-offs, so that a short run sees many changes."""
    roam = dict(claim_median=2, away_median=3, handoff_prob=0.3) if dense else {}
    # each phone has its own host name: two phones with the same name that are never apart for long are taken for one by the rule that joins the cards of a phone (the overlap limit is 30 minutes,
    # and a compressed run lasts a few)
    names = (("c1", "android", ANDROID_MAC, 20, "android-model-1"), ("c2", "ios", IOS_MAC, 21, None), ("c3", "android", "c6:00:00:00:00:23", 22, "android-model-3"))
    with Lan(2) as lan, VedettaProcess(code_dir) as vedetta:
        walks, holder = {}, {}
        for i, (name, kind, mac, number, hostname) in enumerate(names):
            address = lan.add_client(name, mac, number)
            lan.announce(name, kind, mac, address, hostname)
            walks[name] = (address, phases.roam_schedule(random.Random(seed * 100 + i), cycles, **roam))
            holder[name] = None
        vedetta.add_found()
        started = time.time()
        truth = _truth(vedetta, _phones_and_base(names))
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        for cycle in range(cycles):
            for name, (address, walk) in walks.items():
                if walk[cycle] != holder[name]:
                    holder[name] = walk[cycle]
                    lan.hold(name, address, holder[name])
            vedetta.wait_cycles(1)
        vedetta.wait_cycles(SETTLE)
        if not dense:
            time.sleep(330)                                   # 1.0 step P5: one more judgement, so that a repeater linked just before it lends its MAC is held again
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta),
                "links": _links(vedetta, truth, NEVER), "online_share": _online_shares(vedetta, [a for a, _ in walks.values()], started),
                "phones_all": [{"ip": c.get("ip"), "name": c.get("name"), "name_source": c.get("name_source"), "type": c.get("type"), "brand": c.get("brand"), "mobile": c.get("is_mobile"), "online": c.get("online")}
                               for c in vedetta.cards() if (c.get("ip") or "").rsplit(".", 1)[-1] in ("20", "21", "22")],
                "handoffs": sum(a in ("ext", "ext2") and b in ("ext", "ext2") and a != b for _, walk in walks.values() for a, b in zip(walk, walk[1:])),
                "holds": {name: sum(1 for a, b in zip(walk, walk[1:]) if a != b) for name, (_, walk) in walks.items()}}


def _phones_and_base(names: tuple) -> dict:
    """The MAC at each address of S10: the router, the two extenders, the phones."""
    return {**_base_macs(2), **{"%s.%d" % (SUBNET, number): mac for _n, _k, mac, number, _h in names}}


LAPTOP_MAC, CONSOLE_MAC = "3c:00:00:00:00:31", "70:00:00:00:00:32"       # real (not private) MACs: the judgement of "two devices behind a card" is silent for private ones


def _card_at(vedetta: VedettaProcess, address: str) -> list[dict]:
    """The cards at an address, with the notes the card shows about another device behind it."""
    return [{"name": c.get("name"), "name_source": c.get("name_source"), "online": c.get("online"), "brand": c.get("brand"), "type": c.get("type"),
             "notes": {a.get("key"): a.get("value") for a in c.get("attrs") or [] if a.get("key", "").startswith("other_device")}}
            for c in vedetta.cards() if c.get("ip") == address]


LAPTOP_RETURN_ADDRESS = 31


def _console_takes_address(code_dir: str, user_named: bool, laptop_returns: bool) -> dict:
    """A laptop leaves its address and a games console takes it (the router hands it out again). The laptop's card is named by the user (`user_named`) or keeps the name the laptop announced;
    the laptop then comes back (`laptop_returns`) at another address. What does each card say at each step, and does anyone get a card of their own?"""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, address)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: LAPTOP_MAC})
        vedetta.wait_cycles(SETTLE + 1)
        if user_named:
            vedetta.rename(next(c["id"] for c in vedetta.cards() if c.get("ip") == address), "Portatile")
            vedetta.wait_cycles(1)
        before = _card_at(vedetta, address)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", CONSOLE_MAC, 20)
        lan.announce("c2", "console", CONSOLE_MAC, address)
        vedetta.wait_cycles(SETTLE + 3)
        result = {"before": before, "console_on": _card_at(vedetta, address), "cards_total": len(vedetta.cards()), "links": _links(vedetta, truth)}
        if laptop_returns:
            new_address = "%s.%d" % (SUBNET, LAPTOP_RETURN_ADDRESS)
            lan.move("c1", address, new_address)
            lan.link("c1", True)
            lan.announce("c1", "windows", LAPTOP_MAC, new_address)
            vedetta.add_found()
            vedetta.wait_cycles(SETTLE + 2)
            result["laptop_back"] = {"at_old_address": _card_at(vedetta, address), "at_new_address": _card_at(vedetta, new_address), "cards_total": len(vedetta.cards())}
            result["links"] = _links(vedetta, truth)            # never one MAC on two cards
        return result


def s11_console_takes_address(code_dir: str) -> dict:
    """The laptop is named by the user and does not come back (a report of a user: the console showed up as the laptop whenever it was on)."""
    return _console_takes_address(code_dir, user_named=True, laptop_returns=False)


def s11b_laptop_comes_back(code_dir: str) -> dict:
    """As S11, and the laptop comes back at another address: does the card follow it, does the console keep a card of its own?"""
    return _console_takes_address(code_dir, user_named=True, laptop_returns=True)


def s11c_automatic_name(code_dir: str) -> dict:
    """As S11, but the laptop's card keeps the name the laptop announced (nobody named it): the console must not carry on with it."""
    return _console_takes_address(code_dir, user_named=False, laptop_returns=False)


# Any device can take the address of any other: every ordered pair of different kinds (the fingerprints of tools/lansim/fingerprints.py), plus a control of two devices of the SAME kind.
PAIRS = (("android", "ios"), ("ios", "android"), ("windows", "console"), ("console", "camera"), ("camera", "windows"), ("android", "windows"), ("android", "android"))


def _pair(code_dir: str, first: str, second: str) -> dict:
    """The first device announces its own host name, leaves; the second one (another MAC, its own host name) takes the address. What name does the card carry?"""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", "3c:00:00:00:00:51", 20)
        lan.announce("c1", first, "3c:00:00:00:00:51", address, "first-" + first)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: "3c:00:00:00:00:51"})
        vedetta.wait_cycles(SETTLE + 1)
        before = [c["name"] for c in _card_at(vedetta, address)]
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", "70:00:00:00:00:52", 20)
        lan.announce("c2", second, "70:00:00:00:00:52", address, "second-" + second)
        vedetta.wait_cycles(SETTLE + 3)
        after = [c["name"] for c in _card_at(vedetta, address)]
        return {"before": before, "after": after, "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta), "links": _links(vedetta, truth)}


def s13_any_pair(code_dir: str) -> dict:
    """Any device can take the address of any other: after the change the card must carry the name of the device that is there now (not the one announced by the one that left), for every pair of
    different kinds. For two devices of the same kind the two fingerprints are the same, so the rule cannot tell them apart: a known limit, measured here."""
    results = {}
    for first, second in PAIRS:
        results["%s -> %s" % (first, second)] = outcome = _pair(code_dir, first, second)
        print("RESULT %s -> %s: before %s, after %s" % (first, second, outcome["before"], outcome["after"]), flush=True)
    return results


def s13l_link_holds(code_dir: str) -> dict:
    """1.0 step P4: the laptop stays long enough for its card to be linked to its MAC, then leaves and the console takes the address. The link must not follow the address: it stays on
    the laptop, still "linked", and the console is never linked to the card. Step P5 (once the link may be used): the laptop's card goes offline within the tolerance, never takes the
    name, brand or type of the console, and the console has no card of its own (decision 1A: until P7/P9)."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, address)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: LAPTOP_MAC})
        laptop_id = _id_at(vedetta, address)
        _wait_usable(vedetta, laptop_id, USABLE_WAIT_S)
        before, card_before = _card_links(vedetta).get(laptop_id), _card_of(vedetta, laptop_id)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", CONSOLE_MAC, 20)
        lan.announce("c2", "console", CONSOLE_MAC, address)
        seen = _watch(vedetta, laptop_id, SETTLE + 3)
        time.sleep(330)                                       # at least one more judgement of the links with the console at the address
        seen += _watch(vedetta, laptop_id, 1)
        return {"before": before, "after": _card_links(vedetta).get(laptop_id), "laptop": LAPTOP_MAC.upper(), "links": _links(vedetta, truth),
                "card_before": card_before, "seen": seen, "cards_at_address": len(_card_at(vedetta, address))}


def _card_of(vedetta: VedettaProcess, device_id: str | None) -> dict | None:
    """What the card shows: id, address, name, brand, type, online."""
    return next(({k: c.get(k) for k in ("id", "ip", "name", "brand", "type", "online")} for c in vedetta.cards() if c["id"] == device_id), None)


def _watch(vedetta: VedettaProcess, device_id: str | None, cycles: int) -> list[dict]:
    """The card after each of `cycles` cycles."""
    out = []
    for _ in range(cycles):
        vedetta.wait_cycles(1)
        out.append(_card_of(vedetta, device_id))
    return out


def _wait_at(vedetta: VedettaProcess, device_id: str | None, address: str, timeout: float) -> float | None:
    """Seconds until the card is at `address` and online (None if not within `timeout`)."""
    start = time.time()
    while time.time() - start < timeout:
        card = _card_of(vedetta, device_id)
        if card and card["ip"] == address and card["online"]:
            return round(time.time() - start)
        time.sleep(5)
    return None


def _alerts(vedetta: VedettaProcess, key: str) -> int:
    """How many notices of this kind the journal of the run holds."""
    try:
        with open(os.path.join(vedetta.data, "journal.jsonl"), encoding="utf-8") as f:
            return sum(1 for line in f if '"%s"' % key in line)
    except OSError:
        return 0


def s11l_laptop_followed(code_dir: str) -> dict:
    """1.0 step P5, S11B with the link: the laptop (named by the user) is linked and its link may be used; it leaves, the console takes its address, the laptop comes back at
    another address. Its card follows it there (same id, same history, its name) at the next full sweep, without a search by hand; the console never enters the laptop's card."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, address)
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: LAPTOP_MAC})
        laptop_id = _id_at(vedetta, address)
        vedetta.rename(laptop_id, "Portatile")
        usable = _wait_usable(vedetta, laptop_id, USABLE_WAIT_S)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", CONSOLE_MAC, 20)
        lan.announce("c2", "console", CONSOLE_MAC, address)
        seen = _watch(vedetta, laptop_id, SETTLE + 3)
        new_address = "%s.%d" % (SUBNET, LAPTOP_RETURN_ADDRESS)
        lan.move("c1", address, new_address)
        lan.link("c1", True)
        lan.announce("c1", "windows", LAPTOP_MAC, new_address)
        followed = _wait_at(vedetta, laptop_id, new_address, 420)
        seen += _watch(vedetta, laptop_id, 2)
        return {"usable": usable, "followed_s": followed, "card_end": _card_of(vedetta, laptop_id), "laptop_id": laptop_id, "new_address": new_address, "seen": seen,
                "cards_at_old_address": len(_card_at(vedetta, address)), "links": _links(vedetta, truth)}


def s31_swap(code_dir: str) -> dict:
    """1.0 step P5, the case of 4b3f9dc: two devices whose links may be used exchange their addresses. Both cards follow (in one write), keep their names, are never offline
    beyond the tolerance, and each gets one notice of a changed address."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        a = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, a, "laptop-s31")
        b = lan.add_client("c2", ANDROID_MAC, 21)
        lan.announce("c2", "android", ANDROID_MAC, b, "android-s31")
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), a: LAPTOP_MAC, b: ANDROID_MAC})
        ids = {"laptop": _id_at(vedetta, a), "android": _id_at(vedetta, b)}
        usable = all([_wait_usable(vedetta, i, USABLE_WAIT_S) for i in ids.values()])
        names = {k: (_card_of(vedetta, i) or {}).get("name") for k, i in ids.items()}
        spare = "%s.29" % SUBNET
        lan.move("c1", a, spare)
        lan.move("c2", b, a)
        lan.move("c1", spare, b)
        lan.announce("c1", "windows", LAPTOP_MAC, b, "laptop-s31")
        lan.announce("c2", "android", ANDROID_MAC, a, "android-s31")
        seen = []
        for _ in range(SETTLE + 4):
            vedetta.wait_cycles(1)
            seen.append({k: _card_of(vedetta, i) for k, i in ids.items()})
        end = {k: _card_of(vedetta, i) for k, i in ids.items()}
        return {"usable": usable, "end": end, "want": {"laptop": b, "android": a}, "names": names, "alerts": _alerts(vedetta, "alert.ip_changed"),
                "offline_seen": sum(1 for snap in seen for c in snap.values() if c and not c["online"]), "links": _links(vedetta, truth)}


def s32_move(code_dir: str) -> dict:
    """1.0 step P5: a device whose link may be used passes to a free address. Its card follows it within the next full sweep of the network (decision 6A: no extra question),
    with one notice of a changed address."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, address, "laptop-s32")
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: LAPTOP_MAC})
        laptop_id = _id_at(vedetta, address)
        usable = _wait_usable(vedetta, laptop_id, USABLE_WAIT_S)
        new_address = "%s.40" % SUBNET
        lan.move("c1", address, new_address)
        lan.announce("c1", "windows", LAPTOP_MAC, new_address, "laptop-s32")
        followed = _wait_at(vedetta, laptop_id, new_address, 420)
        vedetta.wait_cycles(1)
        return {"usable": usable, "followed_s": followed, "card_end": _card_of(vedetta, laptop_id), "new_address": new_address,
                "alerts": _alerts(vedetta, "alert.ip_changed"), "links": _links(vedetta, truth)}


BLINK_TV_MAC = "3c:00:00:00:00:81"
AWAY_CYCLES = 30       # S35: cycles the TV is away after it was listed (about 8 minutes: more than one full sweep of the network)


def _listed(vedetta: VedettaProcess, mac: str) -> bool:
    return mac.upper() in {str(d.get("mac") or "").upper() for d in vedetta.get("/api/new-devices")}


def _wait_listed(vedetta: VedettaProcess, mac: str, timeout: float) -> float | None:
    """Seconds until `mac` is in the list of new devices (None if not within `timeout`)."""
    start = time.time()
    while time.time() - start < timeout:
        if _listed(vedetta, mac):
            return round(time.time() - start)
        time.sleep(5)
    return None


def s35_tv_away_stays_listed(code_dir: str) -> dict:
    """1.0 step P7: a new device (a TV nobody added) is seen, then leaves for longer than a full sweep. With the inventory it stays in the list of
    new devices while away (decision 3A: asleep, "seen X ago"); before, it disappeared at the next sweep and came back with it."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE)
        lan.add_client("tv", BLINK_TV_MAC, 50)
        first = _wait_listed(vedetta, BLINK_TV_MAC, 420)
        lan.link("tv", False)
        away = []
        for _ in range(AWAY_CYCLES):
            vedetta.wait_cycles(1)
            away.append(_listed(vedetta, BLINK_TV_MAC))
        return {"first_listed_s": first, "listed_away": away}


def s36_console_at_linked_address(code_dir: str) -> dict:
    """1.0 step P7: the laptop's card is linked; the laptop leaves and the console takes its address. The console is a new device (decision 2A:
    "configured by address" only for the cards without a link); before, it stayed hidden behind the laptop's card."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", LAPTOP_MAC, 20)
        lan.announce("c1", "windows", LAPTOP_MAC, address, "laptop-s36")
        vedetta.add_found()
        laptop_id = _id_at(vedetta, address)
        usable = _wait_usable(vedetta, laptop_id, USABLE_WAIT_S)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", CONSOLE_MAC, 20)
        lan.announce("c2", "console", CONSOLE_MAC, address)
        return {"usable": usable, "console_listed_s": _wait_listed(vedetta, CONSOLE_MAC, 420)}


STRANGER_MAC = "3c:00:00:00:00:91"
ROUND_S = 300          # P8: every address of the network is asked within this (arpplan.ROUND_S)


def s37_new_device_found_by_the_slices(code_dir: str) -> dict:
    """1.0 step P8: after the first search a device nobody knows joins at a high address (outside the first slices). The turn of the slices
    finds it and lists it as new within a round (5 minutes) and a cycle, without any search by hand."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE)
        lan.add_client("stranger", STRANGER_MAC, 230)
        return {"listed_s": _wait_listed(vedetta, STRANGER_MAC, ROUND_S + 120), "round_s": ROUND_S}


PRINTER_MAC, NEW_PRINTER_MAC = "3c:00:00:00:00:61", "3c:00:00:00:00:62"


def s33_replaced(code_dir: str) -> dict:
    """1.0 step P5, decision 2A: the printer (named by the user) is linked and its link may be used; it is replaced by a new one (another MAC, the same address). The card goes
    offline; once the new one has answered for two judgements the card offers the gesture "this is a new device"; sent through the API, the card is online again with the new
    device, the same id and name, and its link passes to the new MAC (source "user")."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", PRINTER_MAC, 20)
        lan.announce("c1", "camera", PRINTER_MAC, address, "printer-a")
        vedetta.add_found()
        truth = _truth(vedetta, {**_base_macs(), address: PRINTER_MAC})
        card_id = _id_at(vedetta, address)
        vedetta.rename(card_id, "Stampante")
        usable = _wait_usable(vedetta, card_id, USABLE_WAIT_S)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", NEW_PRINTER_MAC, 20)
        lan.announce("c2", "camera", NEW_PRINTER_MAC, address, "printer-b")
        offered = _wait_offer(vedetta, card_id, 1200)
        offline_before = not (_card_of(vedetta, card_id) or {}).get("online", True)
        sent = bool(offered) and (vedetta.post("/api/devices/%s/relink" % card_id, {}) or {}).get("ok") is True
        vedetta.wait_cycles(SETTLE + 1)
        time.sleep(60)
        row = _card_links(vedetta).get(card_id)
        source = _read_db(vedetta.data, "SELECT device_id, source FROM card_mac", dict).get(card_id)
        return {"usable": usable, "offered": offered, "offline_before": offline_before, "sent": sent, "card_end": _card_of(vedetta, card_id), "card_id": card_id,
                "name": "Stampante", "row_end": [row[0], row[1], source] if row else None, "new_mac": NEW_PRINTER_MAC.upper(), "links": _links(vedetta, {})}


def _wait_offer(vedetta: VedettaProcess, device_id: str | None, timeout: float) -> bool:
    """Waits until the card offers the gesture "this is a new device" (at most `timeout` seconds)."""
    end = time.time() + timeout
    while time.time() < end:
        if device_id and vedetta.get("/api/devices/%s/relink" % device_id).get("offer"):
            return True
        time.sleep(20)
    return False


def _seqs(data: str) -> dict:
    """Device id -> seq, from devices.yaml of the data folder."""
    import yaml
    with open(os.path.join(data, "devices.yaml"), encoding="utf-8") as f:
        return {d["id"]: d.get("seq") for d in (yaml.safe_load(f) or {}).get("devices", [])}


S30_DEVICES = (("c1", "android", ANDROID_MAC, 20, "android-s30"), ("c2", "windows", LAPTOP_MAC, 21, "laptop-s30"), ("c3", "console", CONSOLE_MAC, 22, "console-s30"))


def s30_upgrade_and_back(code_dir: str, old_code_dir: str | None = None, old_minutes: float = 10, back_minutes: float = 5) -> dict:
    """1.0 step P4, an update and a way back with the app running on one data folder: the old version (`old_code_dir`, 0.13.1) for 10 minutes, two devices swapping their addresses
    half way; the new version (the seed of the links); the old one again for 5 minutes, a card removed and added again (same id, new seq); the new one again. Expected: no wrong link,
    no MAC on two cards, no link inherited by the card added again."""
    if not old_code_dir:
        raise RuntimeError("S30 needs the code of the old version (--old-code-dir)")
    data = tempfile.mkdtemp(prefix="lansim-s30-")
    with Lan() as lan:
        for name, kind, mac, number, host in S30_DEVICES:
            lan.announce(name, kind, mac, lan.add_client(name, mac, number), host)
        with VedettaProcess(old_code_dir, data=data) as old:
            old.add_found()
            time.sleep(old_minutes * 30)
            a, b, spare = ("%s.%d" % (SUBNET, n) for n in (20, 21, 29))
            lan.move("c1", a, spare)
            lan.move("c2", b, a)
            lan.move("c1", spare, b)
            lan.announce("c1", "android", ANDROID_MAC, b, "android-s30")
            lan.announce("c2", "windows", LAPTOP_MAC, a, "laptop-s30")
            time.sleep(old_minutes * 30)
        where = {**_base_macs(), SUBNET + ".20": LAPTOP_MAC, SUBNET + ".21": ANDROID_MAC, SUBNET + ".22": CONSOLE_MAC}
        with VedettaProcess(code_dir, data=data) as new:
            new.wait_cycles(SETTLE + 1)
            seed = _links(new, _truth(new, where))
            sources = _sources(data)
        with VedettaProcess(old_code_dir, data=data) as old:
            old.wait_cycles(SETTLE)                           # the cards are listed once the first cycle has run
            removed = _id_at(old, SUBNET + ".22")
            if removed is None:
                raise RuntimeError("S30: no card at .22 after the restart of the old version")
            old.remove(removed)
            old.add_found()
            time.sleep(back_minutes * 60)
        with VedettaProcess(code_dir, data=data) as new:
            new.wait_cycles(SETTLE + 1)
            first = dict(_card_links(new))
            time.sleep(330)                                   # the next judgement: the card added again is judged by itself
            links, rows, seqs = _links(new, _truth(new, where)), _card_links(new), _seqs(data)
    return {"seed": seed, "seed_sources": sources, "removed_row_after_restart": list(first.get(removed) or ()), "links": links,
            "inherited": sum(1 for d, (_m, _s, q, _c) in rows.items() if seqs.get(d) != q), "rows": len(rows)}


def _sources(data: str) -> dict:
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(data, "vedetta.db"), uri=True)
    try:
        return dict(db.execute("SELECT source, COUNT(*) FROM card_mac GROUP BY source").fetchall())
    finally:
        db.close()


CAMERA_MAC = "5a:00:00:00:00:41"
RELAY_MAC = "c6:00:00:00:00:52"


def _found(output: str, address: str) -> bool:
    return any(line.split("	")[0] == address for line in output.splitlines())


def s12_camera_ignores_broadcast(code_dir: str) -> dict:
    """A camera that answers a direct ARP request but not a broadcast one (a report of a user: the camera is reachable, but absent from the search). First: does Vedetta's search find it,
    and what does Vedetta learn about it passively (its DHCP request)? Then every technique that was discussed, one by one, from the machine of Vedetta: which of them sees the camera, with and
    without knowing its MAC beforehand."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        phone = lan.add_client("c1", ANDROID_MAC, 20)
        camera = lan.add_camera("cam", CAMERA_MAC, 30)
        lan.announce("c1", "android", ANDROID_MAC, phone)
        lan.announce("cam", "camera", CAMERA_MAC, camera)
        found = [h["ip"] for h in vedetta.add_found()]
        vedetta.wait_cycles(1)
        scan = ["arp-scan", "-I", "e0", "-q", "--plain", "--retry=2", "--timeout=100"]
        lan.probe("ip", "neigh", "flush", "all")
        techniques = {
            "vedetta quick search (broadcast ARP): control phone found": phone in found,
            "vedetta quick search (broadcast ARP): camera found": camera in found,
            "arp-scan broadcast": _found(lan.probe_output(*scan, camera), camera),
            "arp-scan direct, MAC known (--destaddr)": _found(lan.probe_output(*scan, "--destaddr=" + CAMERA_MAC, camera), camera),
            "ping, nothing known (the kernel asks by broadcast)": lan.probe("ping", "-c", "2", "-W", "1", camera),
            "nmap ping (ARP, broadcast)": "Host is up" in lan.probe_output("nmap", "-sn", "-n", camera),
        }
        lan.probe("ip", "neigh", "replace", camera, "lladdr", CAMERA_MAC, "dev", "e0", "nud", "stale")
        techniques["ping with a stale entry (the kernel re-asks directly)"] = lan.probe("ping", "-c", "2", "-W", "1", camera)
        lan.probe("ip", "neigh", "flush", "all")
        lan.probe("ip", "neigh", "replace", camera, "lladdr", CAMERA_MAC, "dev", "e0", "nud", "permanent")
        techniques["ping with a fixed neighbour entry (MAC known)"] = lan.probe("ping", "-c", "2", "-W", "1", camera)
        techniques["nmap ping with a fixed neighbour entry"] = "Host is up" in lan.probe_output("nmap", "-sn", "-n", camera)
        return {"vedetta_hosts_found": found, "techniques": techniques}


SHARED_GAPS = [3, 4, 3, 3, 4, 3, 4, 3, 3, 4, 3, 3, 4]   # the judgments in a row the second device was quiet on a real network (01/11 export)
JUDGE_S = 120                                            # one judgment of the network doctor every two minutes (ha/health_view.py REFRESH_S)
CLOSE_WITHIN = 20                                        # judgments to wait for the finding to close once the relay is gone (40 minutes of the fake clock)


def _old_signal(output: str) -> dict:
    """The signal H20 read before 1.0 step P3, rebuilt here from the DUP lines of one arp-scan (not by the app): several MACs on one address, none of which
    also answers for other addresses. Only for the comparison: it shows the reopenings the single verdict avoids."""
    macs_by_ip: dict[str, set] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].count(".") == 3:
            macs_by_ip.setdefault(parts[0], set()).add(parts[1].upper())
    ips_of: dict[str, set] = {}
    for ip, macs in macs_by_ip.items():
        for mac in macs:
            ips_of.setdefault(mac, set()).add(ip)
    return {ip: sorted(m) for ip, m in macs_by_ip.items() if len(m) > 1 and all(len(ips_of[x]) == 1 for x in m)}


class _SharedAddress:
    """A camera and a relay on one address of the virtual LAN, and Vedetta's chain of the IP conflict run in this process with a fake clock (one step of
    JUDGE_S per judgment): the real arp-scan, Vedetta's own parsing, the observations stored, the verdict of the cycle (macclassify and its last evidence),
    macverdict, the judge of H20 as it ships. Beside it, the old signal of one scan (_old_signal) judged by H20 as in 0.10.0 (clear_cycles 3) and with the
    patch of 0.12 (clear_cycles 10)."""

    def __init__(self, code_dir: str, lan: Lan) -> None:
        sys.path.insert(0, code_dir)
        os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp(prefix="lansim-s14-"))
        import asyncio
        from app import cardlink, maclayer, macverdict
        from app.health import engine, matrix
        from app.scan import scan_arp
        from app.storage.history import History
        self.asyncio, self.maclayer, self.macverdict, self.scan_arp, self.cardlink = asyncio, maclayer, macverdict, scan_arp, cardlink
        self.fake_card_linked: list[str] = []          # 1.0 step P4: a card at the contested address is never linked
        self.lan = lan
        self.history = History(Path(tempfile.mkdtemp(prefix="lansim-s14-")) / "vedetta.db")
        self.shipped = next(r for r in matrix.load() if r["id"] == "H20")
        self.judges = {"shipped": engine.Engine([self.shipped]),
                       "old signal, clear_cycles 3 (0.10.0)": engine.Engine([dict(self.shipped, params={"min_cycles": 2, "clear_cycles": 3})]),
                       "old signal, clear_cycles 10 (0.12)": engine.Engine([dict(self.shipped, params={"min_cycles": 2, "clear_cycles": 10})])}
        self.changes: dict[str, list] = {k: [] for k in self.judges}
        macverdict.refresh_conflicts([])
        self.start = self.now = time.time()
        self.seen = self.first_changed = 0
        self.first = None
        self.judgments = 0

    def judge(self) -> None:
        output = self.lan.probe_output("arp-scan", "-I", "e0", "-x", "--localnet")
        view = {h["ip"]: h for h in self.scan_arp.parse_arp_scan(output)}
        self.history.observe(self.maclayer.from_arp(view, self.now))
        self.asyncio.run(self.maclayer.store_verdict(self.history, now=self.now))
        old = _old_signal(output)
        self.seen += bool(old)
        host = view.get(SUBNET + ".52")
        if host and self.first and host["mac"] != self.first:
            self.first_changed += 1
        self.first = host["mac"] if host else self.first
        for key, judge_ in self.judges.items():
            signals = {"conflicts": self.macverdict.conflicts(self.now) if key == "shipped" else old}
            self.changes[key] += [(c.change, round(self.now - self.start)) for c in judge_.judge(signals, self.now)]
        self.fake_card_linked += self._fake_card_link()
        self.judgments += 1
        self.now += JUDGE_S

    def _fake_card_link(self) -> list[str]:
        """The rule of the card -> MAC link (cardlink.judge) for a card at the contested address, on the observations and the verdict of the chain: the MACs it would link."""
        sessions = [dict(s, mac=s["mac"].upper()) for s in self.history.sessions(self.now - 7 * 86400)]
        kinds = {m: k for m in {s["mac"] for s in sessions} if (k := self.macverdict.kind(m))}
        card = {"id": "fake", "seq": 1, "ip": SUBNET + ".52", "network": "main", "name": None, "name_mac": None}
        res = self.cardlink.judge([card], {"kinds": kinds, "sessions": sessions, "history": {}, "profiles": {}, "roles": set()}, {}, self.now)
        return [r["mac"] for r in res["write"]]

    def close(self) -> int | None:
        """Judges until the finding of the shipped rule closes (at most CLOSE_WITHIN judgments): seconds of the fake clock from the last judgment with the relay."""
        gone = self.now - JUDGE_S
        for _ in range(CLOSE_WITHIN):
            self.judge()
            if self.changes["shipped"] and self.changes["shipped"][-1][0] == "closed":
                return round(self.now - JUDGE_S - gone)
        return None

    def result(self, **extra) -> dict:
        shipped = self.changes["shipped"]
        opened = next((t for c, t in shipped if c == "opened"), None)
        rows = self.history._db.execute("SELECT COUNT(*) FROM ip_conflict").fetchone()[0]
        return {"changes": {k: [c for c, _ in v] for k, v in self.changes.items()}, "shipped_at_s": shipped, "opened_after_s": opened, "fake_card_linked": sorted(set(self.fake_card_linked)),
                "old_signal_in_scans": "%d of %d" % (self.seen, self.judgments), "first_answer_changed": self.first_changed, "ip_conflict_rows": rows, **extra}


def s14_shared_address(code_dir: str, seed: int = 0) -> dict:
    """A camera and a relay on the same address; the relay does not answer every scan (it leaves for 3 or 4 judgments at a time, as on a real network), then is given another address.
    Since 1.0 step P3 H20 reads the single verdict (see _SharedAddress). Expected: the rule as it ships opens one finding, raises it once and keeps it across the gaps, and closes it once the
    relay is gone for good (within half an hour); the old signal of one scan, with clear_cycles 3, closes and opens again at the gaps."""
    with Lan() as lan:
        lan.add_client("cam", CAMERA_MAC, 52)
        lan.add_client("relay", RELAY_MAC, 52)
        chain = _SharedAddress(code_dir, lan)
        rng = random.Random(seed)
        gaps = SHARED_GAPS if not seed else [rng.randint(2, 5) for _ in SHARED_GAPS]     # a campaign varies the gaps (always shorter than the closing of H20)
        for gap in gaps:
            lan.link("relay", True)
            for _ in range(5):
                chain.judge()
            lan.link("relay", False)
            for _ in range(gap):
                chain.judge()
        lan.link("relay", True)
        chain.judge()
        open_before_fix = {k: [f.state for f in j.findings()] for k, j in chain.judges.items()}
        lan.link("relay", False)
        return chain.result(open_before_fix=open_before_fix, closed_after_s=chain.close())


def s14b_slower_relay(code_dir: str, minutes: int = 30) -> dict:
    """As S14, but the relay is always slower than the camera (its answers leave 20 ms later, tc netem) and never goes away: the first answer to every ARP question is always the
    camera's, so the address never changes hands; only the second answer (the DUP line, "also") tells the conflict. Expected: the conflict is seen (opened, raised) and closes once the
    relay is gone for good. Without the second answer (before step P3, G2) the single verdict would never see it."""
    with Lan() as lan:
        lan.add_client("cam", CAMERA_MAC, 52)
        lan.add_client("relay", RELAY_MAC, 52)
        subprocess.run(["ip", "netns", "exec", _ns("relay"), "tc", "qdisc", "add", "dev", "e0", "root", "netem", "delay", "20ms"], check=True, capture_output=True)
        chain = _SharedAddress(code_dir, lan)
        for _ in range(minutes * 60 // JUDGE_S):
            chain.judge()
        open_before_fix = {k: [f.state for f in j.findings()] for k, j in chain.judges.items()}
        lan.link("relay", False)
        return chain.result(open_before_fix=open_before_fix, closed_after_s=chain.close())


def s14c_continuous(code_dir: str, minutes: int = 80) -> dict:
    """A conflict with no gaps at all: the camera and the relay both answer every scan, for `minutes` of the fake clock. Expected: opened within a few minutes (risk R1 of P3: how long the
    single verdict takes to be sure), raised once, never closed."""
    with Lan() as lan:
        lan.add_client("cam", CAMERA_MAC, 52)
        lan.add_client("relay", RELAY_MAC, 52)
        chain = _SharedAddress(code_dir, lan)
        for _ in range(minutes * 60 // JUDGE_S):
            chain.judge()
        return chain.result(open_at_end=[f.state for f in chain.judges["shipped"].findings()])


PLUG_MACS = ["34:94:54:00:00:%02x" % (0x60 + i) for i in range(8)]       # fixed devices (made-up addresses in a plug maker's block); the phones have private MACs
PHONE_MACS = ["c6:00:00:00:00:%02x" % (0x70 + i) for i in range(3)]


def _history(vedetta: VedettaProcess, gateway_ip: str | None = None) -> tuple[list[tuple], list[tuple], set, dict]:
    """What Vedetta recorded: its presence events (device, mac, online, ts), the latency of the card at `gateway_ip`, the phones, and the card id of each address."""
    cards = vedetta.cards()
    by_ip = {c.get("ip"): c["id"] for c in cards}
    db = sqlite3.connect("file:%s?mode=ro" % os.path.join(vedetta.data, "vedetta.db"), uri=True)
    events = [(d, None, o, ts) for d, o, ts in db.execute("SELECT device_id, online, ts FROM presence_events ORDER BY ts, id")]
    latency = db.execute("SELECT ts, ms FROM latency WHERE device_id = ? ORDER BY ts", (by_ip.get(gateway_ip),)).fetchall() if gateway_ip else []
    return events, latency, {c["id"] for c in cards if c.get("is_mobile")}, by_ip


def judged_tail_s(rule: str, code_dir: str) -> float:
    """How long a scenario waits after its last fault so the judge can confirm `rule`: min_cycles judgments in a row, plus one for the judgment that first sees it, every REFRESH_S as in the app.
    Ending earlier leaves the finding opened but never raised (S16 failed this way when the first outage went unseen and the fifth drop came late)."""
    sys.path.insert(0, code_dir)
    from tools import replay_health_engine
    row = next(r for r in replay_health_engine.matrix.load() if r["id"] == rule)
    return (row["params"]["min_cycles"] + 1) * replay_health_engine.REFRESH_S


def _judged(code_dir: str, vedetta: VedettaProcess, since: float, gateway_ip: str | None = None) -> dict:
    """The history of this run judged by the rules on drops and latency as they ship, one judgment every two minutes as in the app (tools/replay_health_engine.py)."""
    sys.path.insert(0, code_dir)
    from tools import replay_health_engine
    events, latency, mobile, by_ip = _history(vedetta, gateway_ip)
    names = {v: k for k, v in by_ip.items()}
    got = replay_health_engine.replay(events, latency, mobile, start=since, end=time.time())
    return {rule: {"raised": [names.get(s, s) for _t, s in r["raised"]], "changes": dict(r["changes"])} for rule, r in got.items()}


def _fixed_and_phones(lan: Lan, vedetta: VedettaProcess, plugs: int, phones: int) -> tuple[list[str], list[str]]:
    """Plugs (fixed devices) at .40 on and Android phones at .60 on, found and added as a user would, and Vedetta told to call a device offline after two missed checks."""
    plug_names = ["plug%d" % i for i in range(plugs)]
    phone_names = ["ph%d" % i for i in range(phones)]
    for i, name in enumerate(plug_names):
        lan.add_client(name, PLUG_MACS[i], 40 + i)
    for i, name in enumerate(phone_names):
        address = lan.add_client(name, PHONE_MACS[i], 60 + i)
        lan.announce(name, "android", PHONE_MACS[i], address)
    vedetta.post("/api/settings", {"miss_limit": 2})
    vedetta.add_found()
    vedetta.wait_cycles(SETTLE + 1)
    return plug_names, phone_names


def s15_drop_together(code_dir: str) -> dict:
    """Six plugs and three phones go off together for 90 seconds (a switch or an access point that restarts); later three plugs and the three phones do. Expected: H06 raised once, for the six
    plugs (the phones are left out); the second time (three fixed devices) nothing."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        plugs, phones = _fixed_and_phones(lan, vedetta, 6, 3)
        since = time.time()
        for group in (plugs + phones, plugs[:3] + phones):
            for name in group:
                lan.link(name, False)
            time.sleep(90)
            for name in group:
                lan.link(name, True)
            time.sleep(420)          # the bins of the first fault are left behind before the second one
        return {"phones_marked": sum(1 for c in vedetta.cards() if c.get("is_mobile")), "judged": _judged(code_dir, vedetta, since)}


def s16_restart_every_150s(code_dir: str) -> dict:
    """A plug and a phone both drop for 60 seconds every 150 seconds, six times (a plug that restarts; a phone whose Wi-Fi sleeps). Expected: H05 raised for the plug, never for the phone."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        plugs, phones = _fixed_and_phones(lan, vedetta, 2, 1)
        since = time.time()
        for _ in range(6):
            lan.link(plugs[0], False)
            lan.link(phones[0], False)
            time.sleep(60)
            lan.link(plugs[0], True)
            lan.link(phones[0], True)
            time.sleep(90)
        time.sleep(max(0.0, judged_tail_s("H05", code_dir) - 90))
        vedetta.wait_cycles(2)
        return {"phones_marked": sum(1 for c in vedetta.cards() if c.get("is_mobile")), "judged": _judged(code_dir, vedetta, since)}


def _median(values: list) -> float | None:
    values = sorted(v for v in values if v is not None)
    return values[len(values) // 2] if values else None


def s17_gateway_slows_down(code_dir: str, baseline_s: int = 4200, slow_s: int = 900) -> dict:
    """The router (the default route of Vedetta's machine) answers in a fraction of a millisecond, then 5 ms later for a quarter of an hour (tc netem on its interface). Expected: H07 raised for the
    gateway during the slow stretch and not before, then closed. Vedetta keeps one latency sample a minute and H07 wants 60 of them before it judges: the quiet stretch lasts 70 minutes
    (with 25 minutes, the first run, it rightly said nothing)."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        lan.probe("ip", "route", "replace", "default", "via", SUBNET + ".1")
        _fixed_and_phones(lan, vedetta, 1, 0)
        since = time.time()
        time.sleep(baseline_s)
        slow_at = time.time()
        subprocess.run(["ip", "netns", "exec", _ns("router"), "tc", "qdisc", "add", "dev", "e0", "root", "netem", "delay", "5ms"], check=True)
        time.sleep(slow_s)
        subprocess.run(["ip", "netns", "exec", _ns("router"), "tc", "qdisc", "del", "dev", "e0", "root"], check=False)
        back_at = time.time()
        time.sleep(600)
        latency = _history(vedetta, SUBNET + ".1")[1]
        return {"latency_ms_median": {"before": _median([ms for ts, ms in latency if ts < slow_at]), "slow": _median([ms for ts, ms in latency if slow_at + 60 <= ts < back_at]),
                                      "after": _median([ms for ts, ms in latency if ts > back_at + 60])},
                "samples": len(latency), "slow_from_s": round(slow_at - since), "slow_until_s": round(back_at - since), "judged": _judged(code_dir, vedetta, since, SUBNET + ".1")}


SCENARIOS = {"S1": s1_stable, "S4": s4_extender_holds, "S5": s5_inherited_name, "S10": s10_two_extenders, "S11": s11_console_takes_address, "S11B": s11b_laptop_comes_back, "S11C": s11c_automatic_name, "S12": s12_camera_ignores_broadcast, "S13": s13_any_pair, "S13L": s13l_link_holds, "S11L": s11l_laptop_followed, "S31": s31_swap, "S32": s32_move, "S33": s33_replaced, "S35": s35_tv_away_stays_listed, "S37": s37_new_device_found_by_the_slices, "S36": s36_console_at_linked_address, "S30": s30_upgrade_and_back, "S14": s14_shared_address, "S14B": s14b_slower_relay, "S14C": s14c_continuous, "S15": s15_drop_together, "S16": s16_restart_every_150s, "S17": s17_gateway_slows_down, "S10D": lambda code_dir: s10_two_extenders(code_dir, dense=True)}
