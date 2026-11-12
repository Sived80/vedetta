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
from tools.lansim.lan import SUBNET, Lan
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
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta)}


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
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta),
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
        return {"before": before, "after": after, "cards_total": len(vedetta.cards()), "ip_conflict_rows": _ip_conflict_rows(vedetta)}


def s13_any_pair(code_dir: str) -> dict:
    """Any device can take the address of any other: after the change the card must carry the name of the device that is there now (not the one announced by the one that left), for every pair of
    different kinds. For two devices of the same kind the two fingerprints are the same, so the rule cannot tell them apart: a known limit, measured here."""
    results = {}
    for first, second in PAIRS:
        results["%s -> %s" % (first, second)] = outcome = _pair(code_dir, first, second)
        print("RESULT %s -> %s: before %s, after %s" % (first, second, outcome["before"], outcome["after"]), flush=True)
    return results


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
        from app import maclayer, macverdict
        from app.health import engine, matrix
        from app.scan import scan_arp
        from app.storage.history import History
        self.asyncio, self.maclayer, self.macverdict, self.scan_arp = asyncio, maclayer, macverdict, scan_arp
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
        self.judgments += 1
        self.now += JUDGE_S

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
        return {"changes": {k: [c for c, _ in v] for k, v in self.changes.items()}, "shipped_at_s": shipped, "opened_after_s": opened,
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
        subprocess.run(["ip", "netns", "exec", "ls-relay", "tc", "qdisc", "add", "dev", "e0", "root", "netem", "delay", "20ms"], check=True, capture_output=True)
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
        subprocess.run(["ip", "netns", "exec", "ls-router", "tc", "qdisc", "add", "dev", "e0", "root", "netem", "delay", "5ms"], check=True)
        time.sleep(slow_s)
        subprocess.run(["ip", "netns", "exec", "ls-router", "tc", "qdisc", "del", "dev", "e0", "root"], check=False)
        back_at = time.time()
        time.sleep(600)
        latency = _history(vedetta, SUBNET + ".1")[1]
        return {"latency_ms_median": {"before": _median([ms for ts, ms in latency if ts < slow_at]), "slow": _median([ms for ts, ms in latency if slow_at + 60 <= ts < back_at]),
                                      "after": _median([ms for ts, ms in latency if ts > back_at + 60])},
                "samples": len(latency), "slow_from_s": round(slow_at - since), "slow_until_s": round(back_at - since), "judged": _judged(code_dir, vedetta, since, SUBNET + ".1")}


SCENARIOS = {"S1": s1_stable, "S4": s4_extender_holds, "S5": s5_inherited_name, "S10": s10_two_extenders, "S11": s11_console_takes_address, "S11B": s11b_laptop_comes_back, "S11C": s11c_automatic_name, "S12": s12_camera_ignores_broadcast, "S13": s13_any_pair, "S14": s14_shared_address, "S14B": s14b_slower_relay, "S14C": s14c_continuous, "S15": s15_drop_together, "S16": s16_restart_every_150s, "S17": s17_gateway_slows_down, "S10D": lambda code_dir: s10_two_extenders(code_dir, dense=True)}
