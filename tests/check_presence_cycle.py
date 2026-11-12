"""The presence by MAC inside one cycle of the check (state_cycle, 1.0 step P5):
  - what each probe is told: its usable link (or none) and the usable links of the other cards, built by one helper for the cycle and for the
    refresh of a single card (state.refresh_device);
  - a linked card whose MAC answers alone at another address in THIS cycle is online in the same cycle, even with a tolerance of one miss, and
    the move is planned; an answer the ARP view only remembers from before the cycle never counts (ArpView.answered_since);
  - the card whose address the moving MAC took is not kept online by it (the guard of the cards without a usable link);
  - a card whose link may not be used (too young) keeps the rule of before.
The network is faked (the probe keeps only the step that decides presence: scan/presence.complete_with_arp)."""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

import yaml

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import linkview, macverdict, netutil, state as state_mod, state_cycle  # noqa: E402
from app.arpview import ArpView  # noqa: E402
from app.scan import latency, presence, probe  # noqa: E402
from app.storage import devices_config  # noqa: E402

NET = "10.0.70.0/24"
M_LAPTOP, M_CONSOLE, M_PRINTER = "02:00:00:00:70:01", "02:00:00:00:70:02", "02:00:00:00:70:03"
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
CARDS = [{"id": "laptop", "ip": "10.0.70.11", "seq": 1, "name": "Laptop"}, {"id": "console", "ip": "10.0.70.12", "seq": 2, "name": "Console"},
         {"id": "printer", "ip": "10.0.70.13", "seq": 3, "name": "Printer"}]
devices_config.DEVICES_PATH.write_text(yaml.safe_dump({"devices": CARDS}), encoding="utf-8")
netutil.last_network = NET
macverdict.refresh({})
NOW = time.time()


def row(device_id, mac, seq, changed=NOW - 3600):
    return {"device_id": device_id, "seq": seq, "network": "main", "mac": mac, "state": "linked", "reason": None, "source": "rule",
            "ip": None, "since": changed, "changed": changed}


linkview.refresh({"laptop": row("laptop", M_LAPTOP, 1), "printer": row("printer", M_PRINTER, 3, changed=NOW - 300)}, judged_at=NOW - 60)

# --- 1. what each probe is told
st = state_mod.DeviceState()
st._last_mac = {"console": "02:00:00:00:70:99", "laptop": "02:00:00:00:70:98"}
told = {i["id"]: i for i in state_cycle.probe_inputs(st, devices_config.load_devices())}
assert told["laptop"]["link"] == M_LAPTOP and told["laptop"]["last_mac"] == M_LAPTOP, "a linked card: its link is its MAC"
assert told["laptop"]["links_of_others"] == frozenset(), told["laptop"]
assert told["console"]["link"] is None and told["console"]["last_mac"] == "02:00:00:00:70:99"
assert told["console"]["links_of_others"] == frozenset({M_LAPTOP.lower()})
assert told["printer"]["link"] is None, "a link of 5 minutes is not used yet (two judgements)"
assert not {"mac_owner", "mac_shared"} & set(told["laptop"]), "the old view of the last MACs is gone"
one = state_cycle.probe_input(st, CARDS[1], devices_config.load_devices())
assert one == told["console"], one
netutil.last_network = None
assert all(i["link"] is None for i in state_cycle.probe_inputs(st, devices_config.load_devices())), "no network read yet: no link is used"
netutil.last_network = NET

# --- 2. the view: only the answers of this cycle
view = ArpView(lambda fresh: None)
view.mem = {"10.0.70.40": (NOW - 400, {"mac": M_LAPTOP}), "10.0.70.41": (NOW + 1, {"mac": M_CONSOLE})}
assert view.answered_since(NOW) == {"10.0.70.41": {"mac": M_CONSOLE}}
assert view.answered_since(NOW - 500) == {"10.0.70.40": {"mac": M_LAPTOP}, "10.0.70.41": {"mac": M_CONSOLE}}


# --- 3. one cycle: the laptop went to 10.0.70.50, the console took the laptop's old address
async def fake_probe(config, arp_task):
    res = await presence.complete_with_arp({"online": False}, config, config["ip"], arp_task)
    return {"id": config["id"], **res}


async def no_latency(targets):
    return {}


def cycle(table, fresh, before=()):
    """One cycle with this ARP view: `fresh` addresses answered in this cycle, `before` ones only remembered from an earlier sweep."""
    async def arp(max_age):
        t = time.time()
        st._view.mem = {ip: (t - 1000 if ip in before else t + 0.001, h) for ip, h in table.items()}
        return table

    async def nothing(*a):
        return None

    async def after(state, arp_view, moves):
        MOVES.clear()
        MOVES.update(moves)
    st._arp_by_ip = arp
    st._save_latency = nothing
    state_cycle._after_cycle = after
    asyncio.run(st.poll_once())


MOVES: dict = {}


probe.probe_device = fake_probe
latency.measure_many = no_latency
TALLY = linkview.tally()
st._miss_limit = lambda: 1                    # the strictest tolerance: one miss is offline
st._record_presence = lambda *a: None
st._shadow = lambda *a: None
cycle({"10.0.70.11": {"mac": M_LAPTOP}, "10.0.70.12": {"mac": M_CONSOLE}}, fresh=True)
assert st.devices["laptop"]["online"] and st.devices["console"]["online"]
cycle({"10.0.70.11": {"mac": M_CONSOLE}, "10.0.70.50": {"mac": M_LAPTOP}}, fresh=True)
assert st.devices["laptop"]["online"] and st.devices["laptop"]["mac"] == M_LAPTOP, ("online in the same cycle, by its MAC", st.devices["laptop"])
assert not st.devices["console"]["online"], "the console's card: its address answers with nobody it may trust"
assert st._last_mac["laptop"] == M_LAPTOP
assert MOVES == {"laptop": "10.0.70.50"}, MOVES
# the same, but the laptop's answer at the new address is only remembered from an earlier sweep: never used
cycle({"10.0.70.11": {"mac": M_CONSOLE}, "10.0.70.50": {"mac": M_LAPTOP}}, fresh=True, before={"10.0.70.50"})
assert not st.devices["laptop"]["online"] and MOVES == {}, (st.devices["laptop"], MOVES)
# another device at the laptop's address and the laptop nowhere: offline (a miss), never online by the console
cycle({"10.0.70.11": {"mac": M_CONSOLE}}, fresh=True)
assert not st.devices["laptop"]["online"] and st.devices["laptop"].get("mac") != M_CONSOLE
# the printer's link is too young: the rule of before (online by whoever answers its address)
cycle({"10.0.70.13": {"mac": M_CONSOLE}}, fresh=True)
assert st.devices["printer"]["online"]
# the counts of the export, over these five cycles: each cycle the laptop's link was used and the printer's was too young; another device
# answered the laptop's address in three; the laptop was found at another address once
got = linkview.tally()
delta = {k: got.get(k, 0) - TALLY.get(k, 0) for k in ("cycles", "used", "other_at_address", "found_elsewhere")}
assert delta == {"cycles": 5, "used": 5, "other_at_address": 3, "found_elsewhere": 1}, delta
assert got["unused"]["young"] - TALLY.get("unused", {}).get("young", 0) == 5, got


# --- 4. the refresh of one card is told the same
async def refresh_case():
    got = []

    async def capture(config, arp_task):
        got.append(config)
        return {"id": config["id"], "online": False}

    async def arp(max_age):
        return {}

    async def measure(config):
        return None
    probe.probe_device = capture
    st._arp_by_ip = arp
    st._measure = measure
    await st.refresh_device("console")
    return got


got = asyncio.run(refresh_case())
assert got and got[0]["link"] is None and got[0]["links_of_others"] == frozenset({M_LAPTOP.lower()}), got
print("TUTTO OK")
