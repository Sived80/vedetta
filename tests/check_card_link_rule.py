"""The card -> MAC link, the pure rule (1.0 step P4): when a card is tied to the MAC that answers at its address, and what happens to a link that
exists. One case per condition of the rule (L1-L9) and per line of what a link does later; then a random test over 2000 made-up histories that
checks the three promises: never one MAC on two cards, never a link when two MACs that are not lent answered the address, never a link to a MAC
that names no single device. Decision 3B (12/11): the card's history counts for the last 7 days, plus a check on the name (L9) that refuses the
link when the card's name, or the judgement of recognition/same_device (policy notify), says an older MAC behind the card was another device."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cardlink  # noqa: E402
from app.recognition import same_device  # noqa: E402

DAY = 86400
NOW = 1_800_000_000.0
M1, M2, M3, REP, PRIV, VR = "02:00:00:00:01:01", "02:00:00:00:01:02", "02:00:00:00:01:03", "02:00:00:00:01:0A", "06:00:00:00:01:05", "00:00:5E:00:01:07"
IP1, IP2, IP3 = "10.0.40.11", "10.0.40.12", "10.0.40.13"


def card(cid, ip, seq=1, network="main", name=None, name_mac=None):
    return {"id": cid, "seq": seq, "ip": ip, "network": network, "name": name, "name_mac": name_mac}


def arp(ip, mac, start=NOW - 3600, end=NOW - 60, source="arp"):
    return {"ip": ip, "mac": mac, "source": source, "start": start, "end": end}


def facts(sessions, kinds=None, history=None, profiles=None, roles=()):
    return {"kinds": kinds or {}, "sessions": sessions, "history": history or {}, "profiles": profiles or {}, "roles": set(roles)}


def run(cards, f, links=None, seeding=False, now=NOW):
    return cardlink.judge(cards, f, links or {}, now, seeding=seeding)


def linked(res):
    return {r["device_id"]: (r["mac"], r["state"]) for r in res["write"]}


BASE = [arp(IP1, M1, NOW - 2 * DAY)]
K = {M1: "normal", M2: "normal", M3: "normal", REP: "lender", PRIV: "private", VR: "virtual"}

# --- L1-L8: a steady device is linked to its MAC, on the network of its address, at the first cycle as "seed"
res = run([card("scan-a", IP1)], facts(BASE, K, {"scan-a": {"recent": {M1}, "older": {M1}}}), seeding=True)
row = res["write"][0]
assert linked(res) == {"scan-a": (M1, "linked")} and res["unlinked"] == {} and res["delete"] == [], res
assert (row["seq"], row["network"], row["source"], row["ip"], row["since"], row["changed"], row["reason"]) == (1, "main", "seed", IP1, NOW, NOW, None), row
assert run([card("scan-a", IP1)], facts(BASE, K, {"scan-a": {"recent": {M1}, "older": {M1}}}))["write"][0]["source"] == "rule"
# a card with no history yet (just added) is judged on the answers alone
assert linked(run([card("scan-a", IP1)], facts(BASE, K))) == {"scan-a": (M1, "linked")}


def reason(cards, f, cid="scan-a", links=None):
    res = run(cards, f, links)
    assert cid not in linked(res), res
    return res["unlinked"][cid]


# L1: no seq, no address, not on the line of a direct network (routed card, proxy ARP of the router, paused network: the caller gives None)
assert reason([card("scan-a", IP1, seq=None)], facts(BASE, K)) == "no_seq"
assert reason([card("scan-a", None)], facts(BASE, K)) == "off_link"
assert reason([card("scan-a", IP1, network=None)], facts(BASE, K)) == "off_link"
# L2: nobody answered; two MACs that are not lent answered (the address went to another device, or a conflict)
assert reason([card("scan-a", IP1)], facts([], K)) == "no_answer"
assert reason([card("scan-a", IP1)], facts(BASE + [arp(IP1, M2, NOW - DAY)], K)) == "several_macs"
assert reason([card("scan-a", IP1)], facts(BASE + [arp(IP1, M2, NOW - DAY, source="arp_dup")], K)) == "several_macs", "a second answer counts"
# a phone behind the repeater: the repeater's lent MAC is left out, the phone's own MAC is the link
PH = [arp(IP2, REP, NOW - 2 * DAY), arp(IP2, M2, NOW - DAY), arp(IP3, REP, NOW - DAY), arp("10.0.40.14", REP, NOW - DAY)]
assert linked(run([card("scan-p", IP2)], facts(PH, K, {"scan-p": {"recent": {M2, REP}, "older": {M2, REP}}}))) == {"scan-p": (M2, "linked")}
# L3: the card of the repeater itself (only the lent MAC answers), a host with two addresses, a conflict, a MAC without verdict
assert reason([card("scan-r", IP3)], facts([arp(IP3, REP, NOW - DAY)], K), "scan-r") == "shared_kind"
assert reason([card("scan-a", IP1)], facts(BASE, {M1: "multi_address"})) == "shared_kind"
assert reason([card("scan-a", IP1)], facts(BASE, {M1: "conflict"})) == "shared_kind"
assert reason([card("scan-a", IP1)], facts(BASE, {})) == "shared_kind", "a MAC without verdict is never linked"
assert reason([card("scan-a", IP1)], facts([arp(IP1, VR, NOW - DAY)], K)) == "shared_kind", "a virtual router MAC names no device"
assert linked(run([card("scan-a", IP1)], facts([arp(IP1, PRIV, NOW - DAY)], K))) == {"scan-a": (PRIV, "linked")}, "a private MAC is a device"
# L4 (7 days): another MAC behind the card in the last week (lent MACs left out); a MAC without verdict counts as another
assert reason([card("scan-a", IP1)], facts(BASE, K, {"scan-a": {"recent": {M1, M2}, "older": {M1, M2}}})) == "history_mixed"
assert reason([card("scan-a", IP1)], facts(BASE, K, {"scan-a": {"recent": {M1, "02:00:00:00:01:99"}, "older": {M1}}})) == "history_mixed"
# L5: one MAC on two cards (a private MAC behind two cards): neither; a MAC already linked to another card: no
TWO = [arp(IP1, PRIV, NOW - DAY), arp(IP2, PRIV, NOW - 3 * DAY, NOW - 2 * DAY)]
KP = {PRIV: "private"}
res = run([card("scan-a", IP1), card("scan-b", IP2)], facts(TWO, KP))
assert linked(res) == {} and res["unlinked"] == {"scan-a": "mac_on_two_cards", "scan-b": "mac_on_two_cards"}, res
held = {"scan-b": {"device_id": "scan-b", "seq": 1, "network": "main", "mac": M1, "state": "held", "reason": "lender", "source": "rule", "ip": IP2,
                   "since": NOW - DAY, "changed": NOW - DAY}}
assert reason([card("scan-a", IP1), card("scan-b", IP2)], facts(BASE, K), links=held) == "mac_on_two_cards"
# L6: DHCP proves another device at the address while M answered (a client behind a repeater without an address of its own)
assert reason([card("scan-a", IP1)], facts(BASE + [{"ip": IP1, "mac": M3, "source": "dhcp", "start": NOW - 120, "end": NOW - 120}], K)) == "dhcp_other"
assert linked(run([card("scan-a", IP1)], facts(BASE + [{"ip": IP1, "mac": M1, "source": "dhcp", "start": NOW - 120, "end": NOW - 120}], K)))
# L7: the card's automatic name was announced by another MAC
assert reason([card("scan-a", IP1, name_mac=M2.lower())], facts(BASE, K)) == "name_other"
assert linked(run([card("scan-a", IP1, name_mac=M1.lower())], facts(BASE, K)))
# L8: M answered for less than two full sweeps, or the MAC layer has less than two full sweeps of data
assert reason([card("scan-a", IP1)], facts([arp(IP1, M1, NOW - 200, NOW - 60)], K)) == "too_soon"
assert cardlink.MIN_ANSWER_S == 300


# --- L9, the name check of decision 3B: an older MAC behind the card (more than 7 days ago)
def prof(mac, **kw):
    return same_device.profile(mac.lower(), private=mac[1] in "26AE", **kw)


LAPTOP, CONSOLE = "00:11:22:00:01:01", "00:11:22:00:01:02"
KL = {LAPTOP: "normal", CONSOLE: "normal"}
P = {LAPTOP: prof(LAPTOP, family="windows", dhcp_name="desk-1"), CONSOLE: prof(CONSOLE, family="console", dhcp_name="ps-1")}
OLD = {"scan-l": {"recent": {CONSOLE}, "older": {LAPTOP, CONSOLE}}}
# the risky case: «Portatile» named by hand for the laptop, gone three weeks ago; the console has the address since: two families say two devices
assert reason([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, CONSOLE, NOW - 6 * DAY)], KL, OLD, P), "scan-l") == "name_other"
# the console held the address for a day three weeks ago, the laptop is back: the same judgement says two devices, a hand name cannot say which
OLD2 = {"scan-l": {"recent": {LAPTOP}, "older": {LAPTOP, CONSOLE}}}
assert reason([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, LAPTOP, NOW - 6 * DAY)], KL, OLD2, P), "scan-l") == "name_other"
# ... but when the card's name is the one the laptop itself announces, the name says which: linked
assert linked(run([card("scan-l", IP1, name="Desk-1")], facts([arp(IP1, LAPTOP, NOW - 6 * DAY)], KL, OLD2, P))) == {"scan-l": (LAPTOP, "linked")}
# the card's name is the one the older MAC announces: not linked to the new one, whatever the judgement says
P3 = {LAPTOP: prof(LAPTOP, dhcp_name="desk-1"), CONSOLE: prof(CONSOLE)}
assert reason([card("scan-l", IP1, name="desk-1")], facts([arp(IP1, CONSOLE, NOW - 6 * DAY)], KL, OLD, P3), "scan-l") == "name_other"
# the older MAC is the same device (same DHCP name): linked; nothing proves two devices (a private MAC vetoes the judgement): linked
P4 = {LAPTOP: prof(LAPTOP, family="windows", dhcp_name="desk-1"), CONSOLE: prof(CONSOLE, family="console", dhcp_name="desk-1")}
assert linked(run([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, CONSOLE, NOW - 6 * DAY)], KL, OLD, P4)))
P5 = {LAPTOP: prof(LAPTOP, family="windows", dhcp_name="desk-1"), PRIV: prof(PRIV, family="ios")}
assert linked(run([card("scan-l", IP1, name="Telefono")], facts([arp(IP1, PRIV, NOW - 6 * DAY)], {PRIV: "private", LAPTOP: "normal"},
                                                               {"scan-l": {"recent": {PRIV}, "older": {LAPTOP, PRIV}}}, P5)))
# a lent MAC in the older history is not "another device"; a network role vetoes the judgement (the same vetoes as the notice)
assert linked(run([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, LAPTOP, NOW - 6 * DAY)], {**KL, REP: "lender"},
                                                                 {"scan-l": {"recent": {LAPTOP}, "older": {LAPTOP, REP}}}, P)))
assert linked(run([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, LAPTOP, NOW - 6 * DAY)], KL, OLD2, P, roles={CONSOLE})))
# an older MAC without a profile cannot be judged: nothing contradicts M
assert linked(run([card("scan-l", IP1, name="Portatile")], facts([arp(IP1, LAPTOP, NOW - 6 * DAY)], KL, OLD2, {})))

# --- a link that exists (3.2)
LINK = {"scan-a": {"device_id": "scan-a", "seq": 1, "network": "main", "mac": M1, "state": "linked", "reason": None, "source": "seed", "ip": IP1,
                   "since": NOW - DAY, "changed": NOW - DAY}}
# unchanged: nothing written
res = run([card("scan-a", IP1)], facts(BASE, K), LINK)
assert res == {"write": [], "delete": [], "unlinked": {}}, res
# the card is gone, or its id now belongs to another card (same id, new seq: removed and added again): the row is deleted
assert run([], facts(BASE, K), LINK)["delete"] == ["scan-a"]
res = run([card("scan-a", IP1, seq=7)], facts(BASE, K), LINK)
assert res["delete"] == ["scan-a"] and "scan-a" not in linked(res), "the old row goes; the new card waits for the next cycle"
# M becomes lent: held with the reason, since kept; then back to linked by itself
res = run([card("scan-a", IP1)], facts(BASE, {M1: "lender"}), LINK, now=NOW + 60)
row = res["write"][0]
assert (row["state"], row["reason"], row["since"], row["changed"], row["mac"]) == ("held", "lender", NOW - DAY, NOW + 60, M1), row
res = run([card("scan-a", IP1)], facts(BASE, K), {"scan-a": row}, now=NOW + 120)
assert (res["write"][0]["state"], res["write"][0]["reason"], res["write"][0]["since"]) == ("linked", None, NOW - DAY)
for k in ("virtual", "multi_address", "conflict"):
    assert run([card("scan-a", IP1)], facts(BASE, {M1: k}), LINK)["write"][0]["reason"] == k
# the card is not on that network any more (the main network moved, or a routed address): held, reason "network"
assert run([card("scan-a", "10.9.0.5", network=None)], facts(BASE, K), LINK)["write"][0]["reason"] == "network"
assert run([card("scan-a", IP1, network="p001")], facts(BASE, K), LINK)["write"][0]["reason"] == "network"
# M out of the window (no verdict: the device is off for a week): the link stays as it is
assert run([card("scan-a", IP1)], facts([], {}), LINK) == {"write": [], "delete": [], "unlinked": {}}
# another MAC takes the address of a linked card: the link is unchanged (that is the case P5 will fix; the link never follows the address)
assert run([card("scan-a", IP1)], facts(BASE + [arp(IP1, M2, NOW - 600)], K, {"scan-a": {"recent": {M1, M2}, "older": {M1, M2}}}), LINK)["write"] == []
# decision 4A: a link never moves to another MAC by itself, even when only another MAC answers for days
assert run([card("scan-a", IP1)], facts([arp(IP1, M2, NOW - 6 * DAY)], K, {"scan-a": {"recent": {M2}, "older": {M2}}}), LINK)["write"] == []

# --- random test: 2000 made-up networks
rnd = random.Random(4)
MACS = [f"02:00:00:00:{i // 256:02X}:{i % 256:02X}" for i in range(12)] + [PRIV, REP, VR]
KINDS = ("normal", "private", "lender", "virtual", "multi_address", "conflict", None)
for _ in range(2000):
    kinds = {m: k for m in MACS if (k := rnd.choice(KINDS))}
    ips = [f"10.0.50.{i}" for i in range(1, 7)]
    sessions = [arp(rnd.choice(ips), rnd.choice(MACS), NOW - rnd.randint(300, 6 * DAY), NOW - rnd.randint(0, 200), rnd.choice(("arp", "arp_dup")))
                for _ in range(rnd.randint(0, 14))]
    cards = [card(f"scan-{i}", ip, seq=i + 1, network=rnd.choice(("main", "main", None))) for i, ip in enumerate(ips)]
    hist = {c["id"]: {"recent": set(rnd.sample(MACS, rnd.randint(0, 2))), "older": set(rnd.sample(MACS, rnd.randint(0, 3)))} for c in cards}
    links = {}
    if rnd.random() < 0.5:
        m = rnd.choice(MACS)
        links["scan-0"] = {"device_id": "scan-0", "seq": 1, "network": "main", "mac": m, "state": "linked", "reason": None, "source": "seed",
                           "ip": ips[0], "since": NOW - DAY, "changed": NOW - DAY}
    res = cardlink.judge(cards, facts(sessions, kinds, hist), links, NOW)
    final = {**links, **{r["device_id"]: r for r in res["write"]}}
    for d in res["delete"]:
        final.pop(d, None)
    pairs = [(r["network"], r["mac"]) for r in final.values()]
    assert len(pairs) == len(set(pairs)), ("one MAC on two cards", final)
    for r in res["write"]:
        if r["device_id"] in links:
            assert r["mac"] == links[r["device_id"]]["mac"], "a link never moves to another MAC"
            continue
        assert r["state"] == "linked" and kinds.get(r["mac"]) in ("normal", "private"), ("a new link only to a MAC of one device", r, kinds.get(r["mac"]))
        ip = next(c["ip"] for c in cards if c["id"] == r["device_id"])
        answered = {s["mac"] for s in sessions if s["ip"] == ip and kinds.get(s["mac"]) not in ("lender", "virtual")}
        assert answered == {r["mac"]}, ("never a link when two MACs that are not lent answered", answered, r)
print("TUTTO OK")
