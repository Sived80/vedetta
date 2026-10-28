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

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
