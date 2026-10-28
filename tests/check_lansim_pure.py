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
for kind in ("android", "ios"):
    p = fingerprints.PROFILES[kind]
    packet = sim_dhcp.client_packet("c6:00:00:00:00:01", 3, p["hostname"], p["vendor_class"], p["prl"], requested_ip="10.9.0.20")
    mac, info = vedetta_dhcp.parse(packet)
    check(kind + " mac", mac, "c6:00:00:00:00:01")
    check(kind + " prl", info.get("prl"), ",".join(str(x) for x in p["prl"]))
    check(kind + " vendor class", info.get("vendor_class"), p["vendor_class"])
    check(kind + " hostname", info.get("hostname"), p["hostname"])
    check(kind + " address asked for", info.get("ip"), "10.9.0.20")
    check(kind + " system read by Vedetta", vedetta_dhcp._os_family(info.get("prl"), info.get("vendor_class")), p["family"])

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

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
