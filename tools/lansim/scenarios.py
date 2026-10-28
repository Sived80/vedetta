"""The scenarios: what happens to the cards of Vedetta when the virtual phones do the things that produce doubles or wrong names. Each scenario builds its own
network and a fresh Vedetta, drives the phones, and returns what the cards say; the expectations are in the docstrings and judged by run_scenarios.py."""
import random

from tools.lansim import phases
from tools.lansim.lan import SUBNET, Lan
from tools.lansim.vedetta_proc import VedettaProcess

ANDROID_MAC, IOS_MAC, IOS_MAC_2 = "c6:00:00:00:00:21", "5a:00:00:00:00:22", "5a:00:00:00:00:24"
SETTLE = 2         # update cycles to wait after a change before looking at the cards


def _phone_cards(vedetta: VedettaProcess) -> list[dict]:
    return sorted(({"ip": c.get("ip"), "name": c.get("name"), "name_source": c.get("name_source"), "online": c.get("online"),
                    "brand": c.get("brand"), "type": c.get("type")} for c in vedetta.cards() if c.get("is_mobile") or c.get("type") == "phone"),
                  key=lambda c: c["ip"] or "")


def s1_stable(code_dir: str) -> dict:
    """An Android phone on the network, nothing happens: one phone card, named as the phone announces itself."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        return {"phones": _phone_cards(vedetta)}


def s4_extender_holds(code_dir: str) -> dict:
    """The extender answers for the phone's address in turns with the phone, several times: still one phone card, the same name, no new card for the extender's MAC."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        for held in (True, False, True, False, True, False):
            lan.hold("c1", address, "ext" if held else None)
            vedetta.wait_cycles(1)
        vedetta.wait_cycles(SETTLE)
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards())}


def s5_inherited_name(code_dir: str) -> dict:
    """An Android phone leaves; an iPhone with a private MAC takes the same address. The card must not carry on with the Android name."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", IOS_MAC, 20)
        lan.announce("c2", "ios", IOS_MAC, address)
        vedetta.wait_cycles(SETTLE + 2)
        return {"before": before, "after": _phone_cards(vedetta)}


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
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        for cycle in range(cycles):
            for name, (address, walk) in walks.items():
                if walk[cycle] != holder[name]:
                    holder[name] = walk[cycle]
                    lan.hold(name, address, holder[name])
            vedetta.wait_cycles(1)
        vedetta.wait_cycles(SETTLE)
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards()),
                "phones_all": [{"ip": c.get("ip"), "name": c.get("name"), "name_source": c.get("name_source"), "type": c.get("type"), "brand": c.get("brand"), "mobile": c.get("is_mobile"), "online": c.get("online")}
                               for c in vedetta.cards() if (c.get("ip") or "").rsplit(".", 1)[-1] in ("20", "21", "22")],
                "handoffs": sum(a in ("ext", "ext2") and b in ("ext", "ext2") and a != b for _, walk in walks.values() for a, b in zip(walk, walk[1:])),
                "holds": {name: sum(1 for a, b in zip(walk, walk[1:]) if a != b) for name, (_, walk) in walks.items()}}


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
        result = {"before": before, "console_on": _card_at(vedetta, address), "cards_total": len(vedetta.cards())}
        if laptop_returns:
            new_address = "%s.%d" % (SUBNET, LAPTOP_RETURN_ADDRESS)
            lan.move("c1", address, new_address)
            lan.link("c1", True)
            lan.announce("c1", "windows", LAPTOP_MAC, new_address)
            vedetta.add_found()
            vedetta.wait_cycles(SETTLE + 2)
            result["laptop_back"] = {"at_old_address": _card_at(vedetta, address), "at_new_address": _card_at(vedetta, new_address), "cards_total": len(vedetta.cards())}
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
        vedetta.wait_cycles(SETTLE + 1)
        before = [c["name"] for c in _card_at(vedetta, address)]
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", "70:00:00:00:00:52", 20)
        lan.announce("c2", second, "70:00:00:00:00:52", address, "second-" + second)
        vedetta.wait_cycles(SETTLE + 3)
        after = [c["name"] for c in _card_at(vedetta, address)]
        return {"before": before, "after": after, "cards_total": len(vedetta.cards())}


def s13_any_pair(code_dir: str) -> dict:
    """Any device can take the address of any other: after the change the card must carry the name of the device that is there now (not the one announced by the one that left), for every pair of
    different kinds. For two devices of the same kind the two fingerprints are the same, so the rule cannot tell them apart: a known limit, measured here."""
    results = {}
    for first, second in PAIRS:
        results["%s -> %s" % (first, second)] = outcome = _pair(code_dir, first, second)
        print("RESULT %s -> %s: before %s, after %s" % (first, second, outcome["before"], outcome["after"]), flush=True)
    return results


CAMERA_MAC = "5a:00:00:00:00:41"


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


SCENARIOS = {"S1": s1_stable, "S4": s4_extender_holds, "S5": s5_inherited_name, "S10": s10_two_extenders, "S11": s11_console_takes_address, "S11B": s11b_laptop_comes_back, "S11C": s11c_automatic_name, "S12": s12_camera_ignores_broadcast, "S13": s13_any_pair, "S10D": lambda code_dir: s10_two_extenders(code_dir, dense=True)}
