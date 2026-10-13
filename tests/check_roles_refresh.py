"""Reference test of roles.refresh (who does what on the network) with every source faked: the first run asks everything (UPnP, ARP, DHCP
discover, the way out to the internet), later runs only the cheap sources, a change is announced once, several DHCP servers raise one alert, and
each failing source is survived (the rest still gives the roles)."""
import asyncio
import pathlib
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import netutil  # noqa: E402
from app.recognition import roles  # noqa: E402
from app.scan import dhcp, discovery  # noqa: E402
from app.storage import journal  # noqa: E402

journal.PATH = Path(tempfile.mkdtemp()) / "journal.jsonl"
calls = {"ssdp": 0, "arp": 0, "dhcp": 0, "net": 0}
events, alerts = [], []
fail = set()


async def fake_net():
    return "192.168.1.0/24", "192.168.1.5"


async def fake_ssdp(own_ip, skip=frozenset()):
    calls["ssdp"] += 1
    if "ssdp" in fail:
        raise RuntimeError("upnp down")
    return {"192.168.1.2": {"types": ["InternetGatewayDevice"], "name": "Router", "model": "R1"}}


class FakeState:
    async def arp_snapshot(self):
        calls["arp"] += 1
        if "arp" in fail:
            raise RuntimeError("arp down")
        return {"192.168.1.2": {"mac": "aa:aa:aa:00:00:02"}, "192.168.1.3": {"mac": "aa:aa:aa:00:00:03"}, "192.168.1.5": {"mac": "aa:aa:aa:00:00:05"}}


async def fake_dhcp_discover():
    calls["dhcp"] += 1
    if "dhcp" in fail:
        raise RuntimeError("no offers")
    return [{"server": "192.168.1.2", "router": ["192.168.1.2"], "dns": ["192.168.1.2"]}] + (
        [{"server": "192.168.1.9"}] if "second_server" in fail else [])


async def fake_check():
    calls["net"] += 1
    if "net" in fail:
        raise RuntimeError("no internet check")
    return {"cgnat": False, "double_nat": False}


async def fake_answers_dns(ip, timeout=1.0):
    return ip in ("192.168.1.2", "192.168.1.5")        # the own address would answer too: it must not be asked


netutil.get_local_network = fake_net
discovery.ssdp_devices = fake_ssdp
roles._rt.dhcp_discover, roles._rt.internet_check = fake_dhcp_discover, fake_check   # main gives roles these two at start-up
roles.answers_dns = fake_answers_dns
roles.default_gateway = lambda: "192.168.1.2"
dhcp.servers.clear()
roles._rt.on_change = events.append
roles._rt.on_alert = lambda msg, key, **p: alerts.append((key, p))
run = lambda: asyncio.new_event_loop().run_until_complete(roles.refresh(FakeState()))   # noqa: E731

run()
assert calls == {"ssdp": 1, "arp": 1, "dhcp": 1, "net": 1}, calls
r = roles.snapshot()
assert set(roles.roles_for("192.168.1.2")) >= {"gateway", "dns", "router"} and roles.roles_for("192.168.1.3") == [], r["by_ip"]
assert "dns" not in roles.roles_for("192.168.1.5"), "the own address is not a candidate DNS server"
assert r["internet"] == {"cgnat": False, "double_nat": False} and len(events) == 2, "the internet check and the roles are announced"
assert events[-1]["type"] == "roles" and alerts == []

run()                                   # nothing changed, discover and internet cached: cheap sources only
assert calls == {"ssdp": 2, "arp": 2, "dhcp": 1, "net": 1}
# nothing is different: no new event and no new journal line (this used to announce "changed" at every refresh)
assert len(events) == 2

# a source fails: the roles are still computed from the others
roles._rt.offers["ts"] = 0.0
roles._rt.internet["ts"] = 0.0
fail.update({"ssdp", "arp", "dhcp", "net"})
run()
assert calls == {"ssdp": 3, "arp": 3, "dhcp": 2, "net": 2} and "gateway" in roles.roles_for("192.168.1.2"), "the default route alone still gives the gateway"
assert len(events) == 3 and events[-1]["type"] == "roles", "the roles really changed (no router any more): announced once"

# two DHCP servers: one alert
fail.clear()
fail.add("second_server")
roles._rt.offers["ts"] = 0.0
run()
assert len(alerts) == 1 and alerts[0][0] == "alert.dhcp_multiple" and "192.168.1.9" in alerts[0][1]["servers"]
# main really gives roles its two active checks (roles no longer imports the scanner)
_main_src = (pathlib.Path(__file__).parent.parent / "vedetta" / "app" / "main.py").read_text(encoding="utf-8")
assert "dhcp_discover=scanner.dhcp_discover" in _main_src and "internet_check=internet.check" in _main_src, "main must give roles its active checks"
print("TUTTO OK")
