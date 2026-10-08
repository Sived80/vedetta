"""The periodic check on a large network, and the guards of its loop.
- a network up to a /24 is asked whole, as always; a wider one by blocks (the network around this machine, the known devices, one more
  block that has waited longest), never more than MAX_TARGETS addresses; a network wider than a /16 is read as the /16 around this machine;
- the database fills in block by block and goes on after a restart; a block asked for the first time is a starting point, not a flood of
  "new devices";
- arp-scan that does not finish is killed; the neighbours the system has seen cost nothing;
- wake-ups of the loop cannot make cycles follow each other without pause, and a chain is written in the log with its causes."""
import asyncio
import ipaddress
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app import state as state_mod  # noqa: E402
from app.scan import arpplan, scanner  # noqa: E402
from app.storage import devices_config, newdevices  # noqa: E402
from app.storage.history import History  # noqa: E402

tmp = Path(tempfile.mkdtemp())
H = History(tmp / "vedetta.db")
state_mod.history = H
newdevices.history = H


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ------------------------------------------------------------------------------------------------------ the plan
assert arpplan.plan("192.168.1.0/24", "192.168.1.5", ["192.168.1.9"], {}) is None, "una /24 si chiede tutta"
assert arpplan.plan("192.168.1.0/28", "192.168.1.5", [], {}) is None, "una rete piu' piccola anche"
p = arpplan.plan("192.168.1.0/24", "192.168.1.5", ["192.168.1.9", "10.9.9.9"], {}, force=True)
assert p["targets"] == ["192.168.1.0/24"] and p["blocks"] == ["192.168.1.0/24"], "force: solo per provarlo, la /24 e' un blocco"
assert arpplan.plan("192.168.1.0/24", None, [], {}, force=True) is None
assert arpplan.plan("non una rete", "10.0.0.1", [], {}) is None, "una rete illeggibile: comportamento di sempre"
assert arpplan.plan("fe80::/64", "fe80::1", [], {}) is None, "IPv6 non e' di questo ARP"

p = arpplan.plan("10.0.0.0/16", "10.0.5.20", ["10.0.9.4", "10.0.5.7", "10.1.0.1", "non un ip"], {})
assert p["blocks"] == ["10.0.5.0/24", "10.0.0.0/24"], p["blocks"]          # own block first, then the first never asked
assert p["targets"] == ["10.0.5.0/24", "10.0.0.0/24", "10.0.9.4"], p["targets"]   # .5.7 is inside the own block, .1.0.1 outside the network
assert p["total"] == 256 and p["done"] == 0 and p["fresh"] == ["10.0.0.0/24"]
ts = {f"10.0.{i}.0/24": 1000.0 + i for i in range(256)}
ts["10.0.77.0/24"] = 10.0                                                  # the one that has waited longest
ts["10.0.5.0/24"] = 1.0                                                    # the own block is asked every time, whatever its age
p = arpplan.plan("10.0.0.0/16", "10.0.5.20", [], ts)
assert p["blocks"] == ["10.0.5.0/24", "10.0.77.0/24"] and p["done"] == 256 and p["fresh"] == []
# going round: asking a block moves it to the back of the queue
for _ in range(300):
    ts[p["blocks"][1]] = time.time() + _
    p = arpplan.plan("10.0.0.0/16", "10.0.5.20", [], ts)
assert len({b for b in ts if ts[b] > 1e9}) >= 255, "in 300 cicli tutti i blocchi sono stati chiesti"

# the cap, whatever the network and the number of known devices
many = [f"10.0.{a}.{b}" for a in range(100, 140) for b in range(1, 200)]
for cidr, own in (("10.0.0.0/16", "10.0.5.20"), ("10.0.0.0/8", "10.0.5.20"), ("172.16.0.0/12", "172.16.9.9"), ("0.0.0.0/0", "10.0.5.20")):
    p = arpplan.plan(cidr, own, many, {})
    n = sum(ipaddress.ip_network(t).num_addresses for t in p["targets"])
    assert n <= arpplan.MAX_TARGETS, (cidr, n)
    assert ipaddress.ip_network(p["network"]).prefixlen >= arpplan.WIDEST_PREFIX, "mai piu' larga di una /16"
    assert all(ipaddress.ip_network(t).subnet_of(ipaddress.ip_network(p["network"])) for t in p["targets"]), "restano dentro la rete"
assert arpplan.plan("10.0.0.0/8", "10.2.3.4", [], {})["network"] == "10.2.0.0/16", "una /8 e' letta come la /16 attorno a noi"
p = arpplan.plan("10.0.0.0/8", None, ["10.1.2.3", "9.9.9.9"], {})
assert p["blocks"] == [] and p["targets"] == ["10.1.2.3"], "senza sapere dove siamo: solo i dispositivi noti"
assert arpplan.own_block_only("10.0.5.20")["targets"] == ["10.0.5.0/24"] and arpplan.own_block_only(None) is None

# the neighbours the system has seen answer
text = ("10.0.5.7 lladdr aa:bb:cc:00:00:07 REACHABLE\n10.0.5.8 lladdr aa:bb:cc:00:00:08 STALE\n10.0.5.9 FAILED\n"
        "10.9.9.9 lladdr aa:bb:cc:00:00:09 REACHABLE\nnon una riga\n10.0.5.10 lladdr rotto REACHABLE\n")
assert [h["ip"] for h in arpplan.parse_neighbors(text)] == ["10.0.5.7", "10.9.9.9"], "solo REACHABLE con un MAC vero"
assert [h["ip"] for h in arpplan.parse_neighbors(text, "10.0.0.0/16")] == ["10.0.5.7"], "e solo dentro la rete"

# ------------------------------------------------------------------------------------------------------ the database
assert H.scan_blocks() == {}
H.scan_blocks_mark({"10.0.0.0/24": 3, "10.0.1.0/24": 0}, 111.0)
H.scan_blocks_mark({"10.0.0.0/24": 5}, 222.0)
assert H.scan_blocks() == {"10.0.0.0/24": 222.0, "10.0.1.0/24": 111.0}, "un blocco chiesto di nuovo si aggiorna"
H2 = History(tmp / "vedetta.db")
assert H2.scan_blocks() == H.scan_blocks(), "dopo un riavvio si riparte da dove si era"

# a block asked for the first time is a baseline, not "new devices"
H.meta_set(newdevices.BASELINE_KEY, "1")
obs = {"AA:BB:CC:00:00:01": {"ip": "10.0.0.5", "vendor": "X", "hostname": None},
       "AA:BB:CC:00:00:02": {"ip": "10.0.9.5", "vendor": "X", "hostname": None}}
fresh, current = newdevices.evaluate(obs, set(), set(), hist=H, baseline_blocks=("10.0.0.0/24",))
assert [f["mac"] for f in fresh] == ["AA:BB:CC:00:00:02"], "solo quello fuori dal blocco al primo giro e' nuovo"
assert H.known_all()["AA:BB:CC:00:00:01"]["status"] == "known"
fresh, _ = newdevices.evaluate({"AA:BB:CC:00:00:03": {"ip": "10.0.0.6", "vendor": "X", "hostname": None}}, set(), set(), hist=H)
assert [f["mac"] for f in fresh] == ["AA:BB:CC:00:00:03"], "gli arrivi successivi nello stesso blocco sono nuovi davvero"


# ------------------------------------------------------------------------------------------------------ arp-scan: stdin, timeout
class FakeProc:
    def __init__(self, hang=False, out=b""):
        self.hang, self.out, self.killed, self.input = hang, out, False, None
        self.returncode = None

    async def communicate(self, input=None):
        self.input = input
        if self.hang:
            await asyncio.sleep(3600)
        return self.out, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


made = []


def fake_exec(hang=False, out=b""):
    async def make(*args, **kwargs):
        proc = FakeProc(hang, out)
        made.append((args, kwargs, proc))
        return proc
    return make


real_exec = asyncio.create_subprocess_exec
try:
    asyncio.create_subprocess_exec = fake_exec(out=b"10.0.5.7\taa:bb:cc:00:00:07\tVendor\n")
    hosts = run(scanner.arp_scan(["10.0.5.0/24", "10.0.9.4"], timeout=5))
    args, kwargs, proc = made[-1]
    assert "--file=-" in args and "--localnet" not in args, args
    assert proc.input == b"10.0.5.0/24\n10.0.9.4" and [h["ip"] for h in hosts] == ["10.0.5.7"], "gli indirizzi vanno sullo standard input"
    run(scanner.arp_scan())
    assert "--localnet" in made[-1][0] and "--file=-" not in made[-1][0], "senza elenco: tutta la rete, come sempre"
    asyncio.create_subprocess_exec = fake_exec(hang=True)
    t0 = time.monotonic()
    try:
        run(scanner.arp_scan(["10.0.5.0/24"], timeout=0.3))
        raise AssertionError("doveva scadere")
    except asyncio.TimeoutError:
        pass
    assert time.monotonic() - t0 < 3 and made[-1][2].killed, "arp-scan che non finisce viene chiuso"
finally:
    asyncio.create_subprocess_exec = real_exec


# ------------------------------------------------------------------------------------------------------ the state on a large network
asked = []
FOUND = {"10.0.5.0/24": ["10.0.5.7"], "10.0.0.0/24": ["10.0.0.9"], "10.0.1.0/24": []}


async def fake_net():
    return "10.0.0.0/16", "10.0.5.20"


async def fake_arp(targets=None, timeout=0):
    asked.append(list(targets) if targets else None)
    hosts = []
    for t in targets or []:
        for ip in FOUND.get(t, [t] if "/" not in t and t in ("10.0.9.4",) else []):
            hosts.append({"ip": ip, "mac": "AA:BB:CC:00:00:" + ip.split(".")[-1].zfill(2), "vendor": None})
    return hosts


async def fake_neigh(net=None):
    return [{"ip": "10.0.77.3", "mac": "AA:BB:CC:00:07:03", "vendor": None}]


H = History(tmp / "state.db")                 # a database of its own: nothing is left over from the checks above
state_mod.history = H
netutil.get_local_network = fake_net
scanner.arp_scan, scanner.neighbors = fake_arp, fake_neigh
devices_config.load_devices = lambda: [{"id": "d1", "ip": "10.0.9.4"}]

st = state_mod.DeviceState()
arp = run(st._arp_by_ip(0))
assert asked[-1] == ["10.0.5.0/24", "10.0.0.0/24", "10.0.9.4"], asked[-1]
assert set(arp) == {"10.0.5.7", "10.0.0.9", "10.0.9.4", "10.0.77.3"}, "chiesti ora + un vicino che il sistema aveva gia' visto"
assert st._baseline_blocks == ("10.0.0.0/24",), "il blocco al primo giro e' un punto di partenza"
assert set(H.scan_blocks()) >= {"10.0.5.0/24", "10.0.0.0/24"}, "i blocchi chiesti sono scritti nel database"
FOUND["10.0.0.0/24"] = []                      # the device of that block has gone: when the block is asked again it leaves the view
arp = run(st._arp_by_ip(0))
assert asked[-1][1] == "10.0.1.0/24" and "10.0.0.9" in arp, "il giro dopo tocca un altro blocco e quello che sa del primo resta"
for _ in range(300):
    arp = run(st._arp_by_ip(0))
assert "10.0.0.9" not in arp, "quando il blocco viene richiesto, chi se n'e' andato esce"
assert all(len(a) <= 1024 for a in asked if a) and all(len(a) <= 4 for a in asked if a), "pochi indirizzi per giro, mai tutta la rete"
assert st._plan_info["total"] == 256 and st._plan_info["done"] >= 255

# the plan itself breaks: only the network around this machine is asked, never the whole /16
asked.clear()
real_plan = arpplan.plan
arpplan.plan = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("guasto"))
try:
    run(st._arp_by_ip(0))
finally:
    arpplan.plan = real_plan
assert asked[-1] == ["10.0.5.0/24"], "se il piano si rompe si chiede solo la rete attorno a noi"

# a normal network is asked whole, as always
async def small_net():
    return "192.168.1.0/24", "192.168.1.5"


netutil.get_local_network = small_net
asked.clear()
st2 = state_mod.DeviceState()
run(st2._arp_by_ip(0))
assert asked == [None], "una /24 si chiede tutta (--localnet), niente blocchi"
assert st2._plan_info is None and st2._arp_mem == {}

# an ARP that does not finish: the cycle goes on with the last result
async def late_arp(targets=None, timeout=0):
    raise asyncio.TimeoutError()


scanner.arp_scan = fake_arp
st3 = state_mod.DeviceState()
run(st3._arp_by_ip(0))
st3._arp = (st3._arp[0] - 100, {"192.168.1.9": {"ip": "192.168.1.9"}})
scanner.arp_scan = late_arp
assert run(st3._arp_by_ip(0)) == {"192.168.1.9": {"ip": "192.168.1.9"}}, "l'ultimo risultato resta"


# ------------------------------------------------------------------------------------------------------ the loop: no chain without pause
async def loop_test():
    state_mod.MIN_GAP_S = 0.3
    st = state_mod.DeviceState()
    st._interval = staticmethod(lambda: 3600)
    started = []

    async def poll_once():
        started.append(time.monotonic())

    st.poll_once = poll_once
    warnings = []
    real_warning = state_mod.logger.warning
    state_mod.logger.warning = lambda msg, *a, **k: warnings.append(msg % a if a else msg)
    task = asyncio.ensure_future(st._loop())
    try:
        await asyncio.sleep(0.2)
        assert len(started) == 1, "il primo giro parte subito"
        for i in range(40):                       # a storm of wake-ups, one every 25 ms, for a second
            st.trigger(reason="ip_changed" if i % 2 else "mqtt")
            await asyncio.sleep(0.025)
        await asyncio.sleep(0.5)
        n = len(started) - 1
        assert 1 <= n <= 7, "40 sveglie in un secondo e mezzo: pochi giri, distanziati (%d)" % n
        gaps = [b - a for a, b in zip(started, started[1:])]
        assert min(gaps) >= 0.25, "mai piu' vicini della distanza minima (%.2f)" % min(gaps)
        assert any("Controlli a catena" in w and "mqtt" in w and "ip_changed" in w for w in warnings), warnings
        assert sum("Controlli a catena" in w for w in warnings) == 1, "l'avviso e' uno solo, non una pioggia"
        before = len(started)
        st.trigger(force=True)
        await asyncio.sleep(0.1)
        assert len(started) == before + 1, "un aggiornamento chiesto dall'utente non aspetta"
    finally:
        task.cancel()
        state_mod.logger.warning = real_warning


run(loop_test())
print("TUTTO OK")
