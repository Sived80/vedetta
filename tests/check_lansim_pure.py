"""The parts of the LAN simulator (tools/lansim) that need no network: the DHCP packets the simulated clients send (they must be read by Vedetta's own
listener exactly as a real phone's), the schedule of the periods in which the extender answers for a client, and the measures that say whether a simulated
network behaves like the real one. The names, MACs and addresses are made up."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import dhcp as vedetta_dhcp  # noqa: E402
from tools.lansim import fingerprints, metrics, phases  # noqa: E402
from tools.lansim import dhcp as sim_dhcp  # noqa: E402

failed = []


def check(label, got, want):
    if got != want:
        failed.append("%s: got %r, expected %r" % (label, got, want))


# --- 1. a simulated client is read by Vedetta's listener like a real one
for kind in ("android", "ios", "windows"):
    p = fingerprints.PROFILES[kind]
    packet = sim_dhcp.client_packet("c6:00:00:00:00:01", 3, p["hostname"], p["vendor_class"], p["prl"], requested_ip="10.9.0.20")
    mac, info = vedetta_dhcp.parse(packet)
    check(kind + " mac", mac, "c6:00:00:00:00:01")
    check(kind + " prl", info.get("prl"), ",".join(str(x) for x in p["prl"]))
    check(kind + " vendor class", info.get("vendor_class"), p["vendor_class"])
    check(kind + " hostname", info.get("hostname"), p["hostname"])
    check(kind + " address asked for", info.get("ip"), "10.9.0.20")
    check(kind + " system read by Vedetta", vedetta_dhcp._os_family(info.get("prl"), info.get("vendor_class")), p["family"])

console = fingerprints.PROFILES["console"]
mac, info = vedetta_dhcp.parse(sim_dhcp.client_packet("70:00:00:00:00:32", 3, console["hostname"], console["vendor_class"], console["prl"], requested_ip="10.9.0.20"))
check("console vendor class", info.get("vendor_class"), "PS5")
check("console is a console for the table of classes", info["vendor_class"].lower().replace(" ", "").startswith(("ps3", "ps4", "ps5")), True)

# the answer of the simulated server: an OFFER/ACK for the client, with the address and the server identifier
offer = sim_dhcp.server_reply(sim_dhcp.client_packet("c6:00:00:00:00:01", 1, None, None, [1, 3]), 2, "10.9.0.20", "10.9.0.1")
check("reply is a reply", offer[0], 2)
check("reply carries the address", ".".join(str(b) for b in offer[16:20]), "10.9.0.20")

# --- 2. the periods in which the extender answers for the client
sched = phases.claim_schedule(random.Random(7), 600)
check("one entry per cycle", len(sched), 600)
check("starts with the client answering", sched[0], False)
check("same seed, same schedule", sched, phases.claim_schedule(random.Random(7), 600))
check("both states happen", (True in sched, False in sched), (True, True))
runs = phases.run_lengths(sched)
check("runs add up", sum(n for _, n in runs), 600)
check("runs alternate", all(a[0] != b[0] for a, b in zip(runs, runs[1:])), True)

# --- 3. the measures, on a hand made timeline: the extender (EXT) takes the address 10.9.0.20 for 3 cycles, twice
EXT = "4e:00:00:00:00:02"
CLI = "c6:00:00:00:00:01"
OTHER = "c6:00:00:00:00:03"
obs = []
for cycle in range(30):
    mac = EXT if cycle in (5, 6, 7, 15, 16, 17) else CLI
    obs.append(metrics.Observation(cycle, "10.9.0.20", mac))
    obs.append(metrics.Observation(cycle, "10.9.0.21", OTHER))
flips = metrics.flips(obs)
check("flips: 4 changes", len(flips), 4)
check("flips: first change", (flips[0].cycle, flips[0].old, flips[0].new), (5, CLI, EXT))
s = metrics.summarize(obs, EXT)
check("all changes involve the extender", s["extender_share"], 1.0)
check("directions are symmetrical", s["symmetry"], 0.0)
check("stays of the extender, in cycles", s["stays"], [3, 3])
check("distinct MACs per changing address", s["macs_per_address"], {"10.9.0.20": 2})
check("addresses where the extender shows up", s["extender_addresses"], 1)

# a timeline with no change: the measures say so instead of failing
quiet = metrics.summarize([metrics.Observation(c, "10.9.0.20", CLI) for c in range(10)], EXT)
check("no flips", quiet["flips"], 0)
verdict = metrics.compare(quiet)
check("a quiet network does not pass", any(not row["ok"] for row in verdict), True)

# the thresholds are those written in the specification sheet
check("thresholds: share", metrics.THRESHOLDS["extender_share"], (0.85, 1.0))
check("thresholds: symmetry", metrics.THRESHOLDS["symmetry"], (0.0, 0.10))

# --- 4. two extenders, at the same distance from the router and far from each other: a phone is held by at most one of them, goes from one to the other
#        directly (a sticky roam) or through a stretch in which it answers itself; the two are used about equally
roam = phases.roam_schedule(random.Random(3), 3000)
check("roam: one entry per cycle", len(roam), 3000)
check("roam: starts with the phone answering", roam[0], None)
check("roam: same seed, same schedule", roam, phases.roam_schedule(random.Random(3), 3000))
check("roam: states", set(roam), {None, "ext", "ext2"})
check("roam: direct hand-offs happen", any(a in ("ext", "ext2") and b in ("ext", "ext2") and a != b for a, b in zip(roam, roam[1:])), True)
check("roam: runs alternate", all(a[0] != b[0] for a, b in zip(phases.run_lengths(roam), phases.run_lengths(roam)[1:])), True)
stretches = [state for seed in range(60) for state, _ in phases.run_lengths(phases.roam_schedule(random.Random(seed), 600)) if state]
share = stretches.count("ext") / len(stretches)
check("roam: the two extenders are used about equally (%.2f)" % share, 0.4 <= share <= 0.6, True)
one = phases.roam_schedule(random.Random(5), 400, extenders=("ext",))
check("roam: with one extender no hand-off", set(one), {None, "ext"})

EXT2 = "4e:00:00:00:00:04"
timeline = []
for cycle in range(12):
    mac = CLI if cycle < 3 or cycle >= 9 else (EXT if cycle < 6 else EXT2)
    timeline.append(metrics.Observation(cycle, "10.9.0.20", mac))
two = metrics.summarize(timeline, (EXT, EXT2))
check("two extenders: flips", two["flips"], 3)
check("two extenders: all involve an extender", two["extender_share"], 1.0)
check("two extenders: symmetrical", two["symmetry"], 0.0)
check("two extenders: one direct hand-off", two["handoffs"], 1)
check("two extenders: stays", two["stays"], [3, 3])
check("two extenders: balance", two["ext_balance"], 0.5)
check("one extender: no balance", metrics.summarize(timeline, EXT)["ext_balance"], None)
check("thresholds for two extenders: balance", metrics.TWO_EXTENDERS["ext_balance"], (0.35, 0.65))
rows = metrics.compare(two, {**metrics.THRESHOLDS, **metrics.TWO_EXTENDERS})
check("compare with two extenders has the balance row", [r["name"] for r in rows if r["name"] == "ext_balance"], ["ext_balance"])

# --- 5. a device that answers a direct ARP request but not a broadcast one (the case of a camera in power saving): the frames it reads and the answer it gives
from tools.lansim import arp  # noqa: E402
CAM_MAC, CAM_IP, ASKER_MAC, ASKER_IP = "5a:00:00:00:00:41", "10.9.0.30", "02:00:00:00:00:02", "10.9.0.2"
direct = arp.request_frame(ASKER_MAC, ASKER_IP, CAM_IP, target_mac=CAM_MAC)
broadcast = arp.request_frame(ASKER_MAC, ASKER_IP, CAM_IP)
check("a broadcast request is a broadcast", arp.is_broadcast(broadcast), True)
check("a direct request is not", arp.is_broadcast(direct), False)
answer = arp.reply_to(direct, CAM_MAC, CAM_IP)
check("a direct request gets an answer", answer is not None, True)
check("the answer is addressed to the asker, from the device", (answer[0:6].hex(), answer[6:12].hex()), (ASKER_MAC.replace(":", ""), CAM_MAC.replace(":", "")))
check("the answer says: this address is at my MAC", (answer[20:22].hex(), answer[22:28].hex(), answer[28:32].hex()), ("0002", CAM_MAC.replace(":", ""), "0a09001e"))
check("a broadcast request gets no answer when broadcasts are ignored", arp.reply_to(broadcast, CAM_MAC, CAM_IP, answer_broadcast=False), None)
check("a broadcast request gets an answer when broadcasts are answered", arp.reply_to(broadcast, CAM_MAC, CAM_IP, answer_broadcast=True) is not None, True)
check("a request for another address gets no answer", arp.reply_to(arp.request_frame(ASKER_MAC, ASKER_IP, "10.9.0.31", target_mac=CAM_MAC), CAM_MAC, CAM_IP), None)
check("an answer (not a request) gets no answer", arp.reply_to(answer, ASKER_MAC, ASKER_IP), None)
check("not ARP at all gets no answer", arp.reply_to(bytes(60), CAM_MAC, CAM_IP), None)
check("a short frame gets no answer", arp.reply_to(direct[:20], CAM_MAC, CAM_IP), None)

# --- 6. S14 (1.0 step P3): the signal H20 read before P3 is rebuilt by the scenario from the DUP lines of one arp-scan, only to compare (the app no longer has it);
# the campaign judges the new runs and checks that the scenarios of repeaters and replaced devices store no conflict
from tools.lansim import run_campaign, scenarios  # noqa: E402
scan = "10.9.0.52\t5a:00:00:00:00:41\tX\n10.9.0.52\tc6:00:00:00:00:52\t(Unknown)\n10.9.0.20\t4e:00:00:00:00:03\t-\n10.9.0.21\t4e:00:00:00:00:03\t-\n" \
       "10.9.0.21\tc6:00:00:00:00:21\t-\nInterface: e0\n"
check("old signal: two MACs on one address, a MAC on two addresses is not", scenarios._old_signal(scan), {"10.9.0.52": ["5A:00:00:00:00:41", "C6:00:00:00:00:52"]})
check("old signal: nothing", scenarios._old_signal(""), {})
check("S14B and S14C are scenarios of the campaign", {"S14B", "S14C"} <= set(scenarios.SCENARIOS) and {"S14B", "S14C"} <= {k for k, _, _ in run_campaign.PLAN}, True)
check("S14C passes when opened and raised and never closed", run_campaign.CHECKS["S14C"]({"changes": {"shipped": ["opened", "raised"]}, "open_at_end": ["active"]})[0], "pass")
check("S14C fails when closed", run_campaign.CHECKS["S14C"]({"changes": {"shipped": ["opened", "raised", "closed"]}, "open_at_end": []})[0], "fail")
check("S14B fails when never seen", run_campaign.CHECKS["S14B"]({"changes": {"shipped": []}})[0], "fail")
check("S4 fails with a stored conflict", run_campaign.CHECKS["S4"]({"before": [{"name": "a"}], "after": [{"name": "a"}], "ip_conflict_rows": 1})[0], "fail")
check("S4 passes without", run_campaign.CHECKS["S4"]({"before": [{"name": "a"}], "after": [{"name": "a"}], "ip_conflict_rows": 0})[0], "pass")
check("S10 fails with a stored conflict", run_campaign.CHECKS["S10"]({"before": [{"name": "a"}], "after": [{"name": "a"}], "ip_conflict_rows": 2})[0], "fail")
check("S13 a replacement stored as a conflict fails", run_campaign._s13({"a -> b": {"before": ["x"], "after": ["y"], "ip_conflict_rows": 1}})[0][1], "fail")
check("S13 a replacement passes", run_campaign._s13({"a -> b": {"before": ["x"], "after": ["y"], "ip_conflict_rows": 0}})[0][1], "pass")

# --- 7. the card -> MAC link (1.0 step P4): what card_mac says, judged against the truth the scenario knows (the device at each address when the cards were added)
PHONE, OTHER, EXT = "c6:00:00:00:00:21", "70:00:00:00:00:32", "4e:00:00:00:00:03"
truth = {"scan-a": PHONE, "scan-b": "02:00:00:00:00:01", "scan-c": "3c:00:00:00:00:31", "scan-e": EXT}
tally = scenarios.link_tally({"scan-a": (PHONE.upper(), "linked", 1), "scan-b": ("02:00:00:00:00:01", "held", 2)}, truth, scenarios.NEVER)
check("link tally: right, held, absent", {k: tally[k] for k in ("right", "wrong", "absent", "held", "two_cards")}, {"right": 1, "wrong": 0, "absent": 2, "held": 1, "two_cards": 0})
check("link tally: the verdict of each card", tally["by_card"], {"scan-a": "right", "scan-b": "held", "scan-c": "absent", "scan-e": "absent"})
tally = scenarios.link_tally({"scan-a": (OTHER, "linked", 1), "scan-e": (EXT, "linked", 2), "scan-x": (EXT, "linked", 3)}, truth, scenarios.NEVER)
check("link tally: the device that came later, and an extender (on its own card too), are wrong", (tally["wrong"], tally["two_cards"]), (3, 1))
check("link tally: a MAC on two cards", scenarios.link_tally({"scan-a": (PHONE, "linked", 1), "scan-c": (PHONE, "linked", 2)}, truth, ())["two_cards"], 1)
check("a link problem fails a run", run_campaign._link_problem({"links": {"wrong": 1, "two_cards": 0}}) != "", True)
check("no link problem", run_campaign._link_problem({"links": {"wrong": 0, "two_cards": 0}}), "")
check("a run without links has no link problem", run_campaign._link_problem({}), "")
check("S1 wants its phone linked", run_campaign.CHECKS["S1"]({"phones": [{}], "phone_link": "absent"})[0], "fail")
check("S1 passes with the phone linked", run_campaign.CHECKS["S1"]({"phones": [{}], "phone_link": "right"})[0], "pass")
check("S13L fails when the laptop was never linked", run_campaign.CHECKS["S13L"]({"before": None, "after": None, "laptop": "L"})[0], "fail")
check("S13L fails when the link moved", run_campaign.CHECKS["S13L"]({"before": ["L", "linked", 1], "after": ["C", "linked", 1], "laptop": "L"})[0], "fail")
check("S30 fails on an inherited link", run_campaign.CHECKS["S30"]({"seed": {"wrong": 0, "two_cards": 0, "right": 2}, "links": {"wrong": 0, "two_cards": 0}, "inherited": 1})[0], "fail")
check("S30 fails without a seed", run_campaign.CHECKS["S30"]({"seed": {"wrong": 0, "two_cards": 0, "right": 0}, "links": {"wrong": 0, "two_cards": 0}, "inherited": 0})[0], "fail")
check("S30 passes", run_campaign.CHECKS["S30"]({"seed": {"wrong": 0, "two_cards": 0, "right": 2}, "links": {"wrong": 0, "two_cards": 0}, "inherited": 0})[0], "pass")
check("S14 fails when the fake card at the contested address was linked", run_campaign.CHECKS["S14"]({"changes": {"shipped": ["opened", "raised", "closed"]}, "fake_card_linked": ["X"]})[0], "fail")
check("S13L and S30 are scenarios of the campaign", {"S13L", "S30"} <= set(scenarios.SCENARIOS) and {"S13L", "S30"} <= {k for k, _, _ in run_campaign.PLAN}, True)

# --- 8. presence by MAC (1.0 step P5): "wrong" counts only the links the app may use (linkview U1-U6, with the same constants), the links stored
# but not usable are counted apart (wrong_stored), so that nothing is hidden; the new scenarios and the new expectations of S13L
from app import linkview  # noqa: E402
check("the same constants as the app", (scenarios.STABLE_S, set(scenarios.HOLD_KINDS)), (linkview.STABLE_S, set(linkview.HOLD_KINDS)))
NOW = 1_800_000_000.0
rows = {"a": (PHONE.upper(), "linked", 1, NOW - 700), "b": (OTHER, "linked", 2, NOW - 100), "c": (OTHER.upper(), "linked", 3, NOW - 900),
        "d": (EXT, "held", 4, NOW - 900), "e": ("02:00:00:00:00:09", "linked", 9, NOW - 900), "f": (EXT.upper(), "linked", 6, NOW - 900)}
usable = scenarios.usable_ids(rows, {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "f": 6}, {EXT.upper(): "lender"}, NOW)
check("usable: linked, same seq, stable for two judgements, its MAC not lent or contested", usable, {"a", "c"})
t = scenarios.link_tally({"scan-a": (OTHER, "linked", 1, NOW - 100), "scan-b": ("02:00:00:00:00:01", "linked", 2, NOW - 900)}, truth, (), usable={"scan-b"})
check("a wrong link not usable yet is counted apart", (t["wrong"], t["wrong_stored"], t["right"]), (0, 1, 1))
t = scenarios.link_tally({"scan-a": (OTHER, "linked", 1, NOW - 900)}, truth, (), usable={"scan-a"})
check("a wrong link that may be used fails", (t["wrong"], t["wrong_stored"]), (1, 1))
t = scenarios.link_tally({"scan-a": (OTHER, "linked", 1)}, truth, ())
check("without the usable links (an older run) every stored link counts", (t["wrong"], t["wrong_stored"]), (1, 1))
check("the counts of a run carry wrong_stored", set(run_campaign._link_counts({"links": {**t}})), {"right", "wrong", "wrong_stored", "absent", "held", "two_cards"})
check("online share from the presence events", scenarios.online_share([(100.0, True), (160.0, False), (190.0, True)], 100.0, 220.0), round(90 / 120, 3))
check("online share: nothing heard", scenarios.online_share([], 100.0, 220.0), 0.0)

L = "3C:00:00:00:00:31"
seen_ok = [{"name": "Laptop", "brand": "B", "type": "laptop", "online": True}, {"name": "Laptop", "brand": "B", "type": "laptop", "online": False}]
base13 = {"before": [L, "linked", 1, 5.0], "after": [L, "linked", 1, 5.0], "laptop": L, "card_before": seen_ok[0], "seen": seen_ok, "cards_at_address": 1}
check("S13L (P5) passes: link kept, the card offline, never the console's name, no card for the console", run_campaign.CHECKS["S13L"](base13)[0], "pass")
check("S13L (P5) fails when the card stays online", run_campaign.CHECKS["S13L"]({**base13, "seen": seen_ok[:1]})[0], "fail")
check("S13L (P5) fails when the card takes the console's name", run_campaign.CHECKS["S13L"]({**base13, "seen": seen_ok + [{**seen_ok[1], "name": "PS5"}]})[0], "fail")
check("S13L (P5) fails when the console gets a card (1A: not before P7)", run_campaign.CHECKS["S13L"]({**base13, "cards_at_address": 2})[0], "fail")
base11 = {"usable": True, "followed_s": 240, "card_end": {"ip": "x.31", "online": True, "name": "Portatile", "id": "L"}, "laptop_id": "L", "new_address": "x.31",
          "seen": [{"name": "Portatile"}], "cards_at_old_address": 0, "links": {"wrong": 0, "two_cards": 0}}
check("S11L passes: the card follows the laptop, keeps its name, the console never in it", run_campaign.CHECKS["S11L"](base11)[0], "pass")
check("S11L fails when the card does not follow", run_campaign.CHECKS["S11L"]({**base11, "followed_s": None})[0], "fail")
check("S11L fails when the console's name shows", run_campaign.CHECKS["S11L"]({**base11, "seen": [{"name": "PS5"}]})[0], "fail")
check("S11L fails when the link was never usable", run_campaign.CHECKS["S11L"]({**base11, "usable": False})[0], "fail")
base31 = {"usable": True, "end": {"A": {"ip": "x.21", "name": "a", "online": True}, "B": {"ip": "x.20", "name": "b", "online": True}},
          "want": {"A": "x.21", "B": "x.20"}, "names": {"A": "a", "B": "b"}, "offline_seen": 0, "alerts": 2}
check("S31 passes: both cards follow, names kept, never offline, a notice each", run_campaign.CHECKS["S31"](base31)[0], "pass")
check("S31 fails when a card stays", run_campaign.CHECKS["S31"]({**base31, "want": {"A": "x.20", "B": "x.20"}})[0], "fail")
check("S31 fails when a card went offline", run_campaign.CHECKS["S31"]({**base31, "offline_seen": 1})[0], "fail")
base32 = {"usable": True, "followed_s": 200, "card_end": {"ip": "x.40", "online": True}, "new_address": "x.40", "alerts": 1}
check("S32 passes: the card follows within the next full sweep, one notice", run_campaign.CHECKS["S32"](base32)[0], "pass")
check("S32 fails when it takes longer than a sweep and a cycle", run_campaign.CHECKS["S32"]({**base32, "followed_s": 400})[0], "fail")
check("S32 fails with no notice", run_campaign.CHECKS["S32"]({**base32, "alerts": 0})[0], "fail")
base33 = {"usable": True, "offline_before": True, "offered": True, "sent": True, "card_end": {"id": "P", "name": "Printer", "online": True},
          "card_id": "P", "name": "Printer", "row_end": ["NEW", "linked", "user"], "new_mac": "NEW"}
check("S33 passes: offline, offered, sent, back online with the new device, history kept", run_campaign.CHECKS["S33"](base33)[0], "pass")
check("S33 fails when not offered", run_campaign.CHECKS["S33"]({**base33, "offered": False})[0], "fail")
check("S33 fails when the link did not pass to the new device", run_campaign.CHECKS["S33"]({**base33, "row_end": ["OLD", "linked", "seed"]})[0], "fail")
check("the new scenarios are in the campaign", {"S11L", "S31", "S32", "S33"} <= set(scenarios.SCENARIOS) and {"S11L", "S31", "S32", "S33"} <= {k for k, _, _ in run_campaign.PLAN}, True)

# --- 9. the single inventory (1.0 step P7): a new device that comes and goes stays in the list (S35); a console that takes a linked laptop's
# address shows up as new (S36)
base35 = {"first_listed_s": 120, "listed_away": [True] * 19 + [False]}
check("S35 passes: listed in at least 90% of the cycles it was away", run_campaign.CHECKS["S35"](base35)[0], "pass")
check("S35 fails below 90%", run_campaign.CHECKS["S35"]({**base35, "listed_away": [True] * 10 + [False] * 10})[0], "fail")
check("S35 fails when never listed", run_campaign.CHECKS["S35"]({**base35, "first_listed_s": None})[0], "fail")
check("S36 passes: the console is a new device", run_campaign.CHECKS["S36"]({"usable": True, "console_listed_s": 300})[0], "pass")
check("S36 fails when the console stays hidden", run_campaign.CHECKS["S36"]({"usable": True, "console_listed_s": None})[0], "fail")
check("S36 fails when the laptop's link was never usable", run_campaign.CHECKS["S36"]({"usable": False, "console_listed_s": 300})[0], "fail")
check("the P7 scenarios are in the campaign", {"S35", "S36"} <= set(scenarios.SCENARIOS) and {"S35", "S36"} <= {k for k, _, _ in run_campaign.PLAN}, True)

# --- 9b. one way to walk the network (1.0 step P8): a device nobody knows is found by the turn of the slices within a round (S37)
check("S37 passes: the new device listed within a round of the slices and a cycle", run_campaign.CHECKS["S37"]({"listed_s": 250, "round_s": 300})[0], "pass")
check("S37 fails when it takes longer", run_campaign.CHECKS["S37"]({"listed_s": 400, "round_s": 300})[0], "fail")
check("S37 fails when never listed", run_campaign.CHECKS["S37"]({"listed_s": None, "round_s": 300})[0], "fail")
check("S37 is in the campaign", "S37" in scenarios.SCENARIOS and "S37" in {k for k, _, _ in run_campaign.PLAN}, True)

# --- 9c. the button shows the inventory (1.0 step P9): the TV that stopped answering is still in its list (S38)
base38 = {"first_listed_s": 60, "in_button": True, "seen_before_press_s": 200}
check("S38 passes: the quiet TV in the button's list, seen before the press", run_campaign.CHECKS["S38"](base38)[0], "pass")
check("S38 fails when the button does not list it", run_campaign.CHECKS["S38"]({**base38, "in_button": False})[0], "fail")
check("S38 fails without the time of the last sight", run_campaign.CHECKS["S38"]({**base38, "seen_before_press_s": None})[0], "fail")
check("S38 is in the campaign", "S38" in scenarios.SCENARIOS and "S38" in {k for k, _, _ in run_campaign.PLAN}, True)

# --- 10. several runs at once (run_campaign --jobs): each run's machines carry its letter, nothing else in the simulator names them by hand
import subprocess  # noqa: E402
ROOT = os.path.join(os.path.dirname(__file__), "..")


def _ns_with(letter):
    env = {**os.environ, "LANSIM_RUN": letter} if letter else {k: v for k, v in os.environ.items() if k != "LANSIM_RUN"}
    code = "from tools.lansim.lan import _ns, PREFIX; print(_ns('vedetta'), PREFIX)"
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env, capture_output=True, text=True).stdout.split()


check("one run: the names of always", _ns_with(""), ["ls-vedetta", "ls-"])
check("run b: its own names", _ns_with("b"), ["lsb-vedetta", "lsb-"])
for name in ("scenarios.py", "vedetta_proc.py", "run_campaign.py", "run_scenarios.py", "run_similarity.py"):
    text = open(os.path.join(ROOT, "tools", "lansim", name), encoding="utf-8").read()
    check("no namespace written by hand in " + name, '"ls-' in text, False)
plan = run_campaign.jobs(quick=True)
fast = run_campaign.jobs(quick=True, slow_first=True)
check("--jobs runs the same runs", sorted(map(repr, fast)), sorted(map(repr, plan)))
check("--jobs starts the longest first", [k for k, _ in fast[:3]], list(run_campaign.SLOW_FIRST))
check("one at a time keeps the order of the plan", [k for k, _ in plan[:2]], ["S14", "S14B"])
check("the ceiling is at most 8 and at most half the threads", 1 <= run_campaign.MAX_JOBS <= min(8, max(1, (os.cpu_count() or 2) // 2)), True)
check("the full plan has every run", len(run_campaign.jobs(quick=False)), sum(r for _, r, _ in run_campaign.PLAN))

# --- S16: after the last outage the scenario waits until the judge can confirm H05 (min_cycles + 1 judgments), from the rule's own numbers
from tools.lansim import scenarios  # noqa: E402
from tools import replay_health_engine as rhe  # noqa: E402
h05 = next(r for r in rhe.matrix.load() if r["id"] == "H05")
check("the wait for H05 comes from its numbers", scenarios.judged_tail_s("H05", ROOT), (h05["params"]["min_cycles"] + 1) * rhe.REFRESH_S)
check("S16 waits for it after the last outage", "judged_tail_s(\"H05\"" in open(os.path.join(ROOT, "tools", "lansim", "scenarios.py"), encoding="utf-8").read(), True)

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
