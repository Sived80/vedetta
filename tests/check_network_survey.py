"""The network survey of the developer export (export/network_survey.py): what it reads about the host and about the network trackers of Home Assistant,
that nothing is left in it that was not meant to be (entity ids, titles, the trackers of Vedetta itself), that what the person's names and addresses
become under the masking, and that the only thing it ever asks Home Assistant is a template (a read)."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize, network_survey as ns  # noqa: E402

# --- the host: VLAN sub-interfaces, bridges, the default gateway (files only: BusyBox has no `ip -j`)
VLAN_CONFIG = "VLAN Dev name\t | VLAN ID\nName-Type: VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD\neth0.10        | 10  | eth0\neth0.20        | 20  | eth0\n"
assert ns.parse_vlan_config(VLAN_CONFIG) == {"eth0.10": {"id": 10, "parent": "eth0"}, "eth0.20": {"id": 20, "parent": "eth0"}}
assert ns.parse_vlan_config("") == {} and ns.parse_vlan_config("garbage | x | y\n") == {}
ROUTE = "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\tMTU\tWindow\tIRTT\neth0\t00000000\t0164A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
assert ns.default_gateway(ROUTE) == "192.168.100.1" and ns.default_gateway("Iface\n") is None

root = Path(tempfile.mkdtemp())
for name, state, mac in (("eth0", "up", "02:11:22:33:44:55"), ("eth0.10", "up", "02:11:22:33:44:55"), ("br0", "down", "02:aa:bb:cc:dd:ee"), ("lo", "unknown", "00:00:00:00:00:00")):
    (root / "sys" / name).mkdir(parents=True)
    (root / "sys" / name / "operstate").write_text(state + "\n")
    (root / "sys" / name / "address").write_text(mac + "\n")
(root / "sys" / "br0" / "bridge").mkdir()
(root / "proc" / "net" / "vlan").mkdir(parents=True)
(root / "proc" / "net" / "vlan" / "config").write_text(VLAN_CONFIG)
(root / "proc" / "net" / "route").write_text(ROUTE)
host = ns.read_host(root / "sys", root / "proc", ipv4_of=lambda n: [{"address": "192.168.100.5", "prefix": 24}] if n == "eth0" else [])
kinds = {i["name"]: i["kind"] for i in host["interfaces"]}
assert kinds == {"br0": "bridge", "eth0": "other", "eth0.10": "vlan", "lo": "loopback"}, kinds
vlan = next(i for i in host["interfaces"] if i["name"] == "eth0.10")
assert vlan["vlan"] == {"id": 10, "parent": "eth0"} and next(i for i in host["interfaces"] if i["name"] == "eth0")["ipv4"][0]["prefix"] == 24
assert host["gateway"] == "192.168.100.1" and host["default_interface"] == "eth0"
assert ns.read_host(root / "missing", root / "missing")["interfaces"] == []             # a host that cannot be read says so, it does not fail

# --- the registry of Home Assistant (what the entities, the devices and the entries say)
ENTITIES = [
    {"entity_id": "device_tracker.leo_phone", "platform": "unifi", "device_id": "d1", "disabled_by": None},
    {"entity_id": "device_tracker.guest_tv", "platform": "unifi", "device_id": "d2", "disabled_by": None},
    {"entity_id": "device_tracker.old_one", "platform": "unifi", "device_id": "d3", "disabled_by": "user"},
    {"entity_id": "device_tracker.vedetta_nas", "platform": "mqtt", "device_id": "dv", "disabled_by": None},
    {"entity_id": "sensor.uptime", "platform": "unifi", "device_id": "d1", "disabled_by": None},
]
DEVICES = [
    {"id": "d1", "config_entries": ["e1"], "identifiers": [["unifi", "x"]], "via_device_id": "d9"},
    {"id": "d2", "config_entries": ["e1"], "identifiers": [["unifi", "y"]], "via_device_id": None},
    {"id": "d3", "config_entries": ["e1"], "identifiers": [], "via_device_id": None},
    {"id": "dv", "config_entries": ["e2"], "identifiers": [["mqtt", "vedetta_nas"]], "via_device_id": None},
]
ENTRIES = [{"entry_id": "e1", "domain": "unifi", "title": "Leo's router", "state": "loaded", "disabled_by": None},
           {"entry_id": "e2", "domain": "mqtt", "title": "Mosquitto", "state": "loaded", "disabled_by": None}]
REG = {"entities": ENTITIES, "devices": DEVICES, "entries": ENTRIES}
ROWS = [
    {"entity_id": "device_tracker.leo_phone", "state": "home", "ip": "192.168.3.40", "mac": "AA:BB:CC:12:34:56", "host_name": "Leo-iPhone.fritz.nu", "keys": ["ip", "mac", "host_name", "vlan", "essid"]},
    {"entity_id": "device_tracker.guest_tv", "state": "not_home", "ip": "192.168.50.7", "mac": "aa-bb-cc-65-43-21", "host_name": None, "keys": ["ip", "mac", "essid"]},
    {"entity_id": "device_tracker.vedetta_nas", "state": "home", "ip": "192.168.100.9", "mac": "aa:bb:cc:00:00:03", "host_name": "nas", "keys": ["ip", "mac", "latency_ms"]},
    {"entity_id": "device_tracker.old_one", "state": "unavailable", "ip": None, "mac": None, "host_name": "x" * 500 + "‮\n", "keys": []},
]

clients = ns.clients_section(ROWS, ENTITIES, DEVICES, ENTRIES)
assert clients["count"] == 3 and clients["truncated"] is False                                     # the tracker of Vedetta itself is not a client
assert clients["states"] == {"home": 1, "not_home": 1, "other": 1}, clients["states"]
assert clients["by_platform"] == {"unifi": 3} and clients["attribute_keys"] == {"unifi": ["essid", "host_name", "ip", "mac", "vlan"]}, clients
leo = next(r for r in clients["rows"] if r["host_name"] == "Leo-iPhone.fritz.nu")
assert leo == {"platform": "unifi", "state": "home", "ip": "192.168.3.40", "mac": "aa:bb:cc:12:34:56", "host_name": "Leo-iPhone.fritz.nu"}, leo
assert all(len(r["host_name"] or "") <= ns.MAX_TEXT and "\n" not in (r["host_name"] or "") and "‮" not in (r["host_name"] or "") for r in clients["rows"])
cut = ns.clients_section(ROWS, ENTITIES, DEVICES, ENTRIES, limit=1)
assert cut["count"] == 3 and len(cut["rows"]) == 1 and cut["truncated"] is True                    # the count stays true, the rows are limited
assert ns.clients_section([], ENTITIES, DEVICES, ENTRIES)["count"] == 0

integrations = ns.integrations_section(ENTITIES, ENTRIES, clients["by_platform"])
assert integrations == {"unifi": {"trackers": 3, "disabled": 1, "entries": {"loaded": 1}}}, integrations   # only the platforms that have trackers, no titles
assert ns.hierarchy_section(DEVICES) == {"devices": 4, "with_via_device": 1}

survey = ns.build(host, ROWS, REG)
assert set(survey) == {"version", "host", "clients", "integrations", "hierarchy"} and survey["version"] == 1
text = json.dumps(survey)
for forbidden in ("device_tracker.", "Leo's router", "Mosquitto", "vedetta_nas", "entry_id", "entity_id"):             # entity ids, titles and the own trackers never go out
    assert forbidden not in text, forbidden

# --- under the masking: the names, the addresses and the MACs of the clients are replaced, and the check finds nothing left
anon = anonymize.Anonymizer()
ns.register_for_masking(anon, survey)
masked = anon.data(survey)
out = json.dumps(masked)
assert "Leo" not in out and "fritz.nu" not in out and "192.168.3." not in out and "192.168.50." not in out and "192.168.100." not in out, out
assert "aa:bb:cc:12:34:56" not in out and "aa:bb:cc:65:43:21" not in out and "02:11:22:33:44:55" not in out
assert "aa:bb:cc:" in out                                                                          # the maker (first three bytes) stays: it is the clue the debug needs
assert not anon.leaks_data(masked), anon.leaks_data(masked)
hosts = {r["host_name"] for r in masked["clients"]["rows"] if r["host_name"]}
assert len(hosts) == 2 and not any("Leo" in h or "xxxx" in h for h in hosts), hosts                  # one label per client

# --- what is asked of Home Assistant: a template, nothing else, and the answer is read as events
class FakeWs:
    def __init__(self, answers):
        self.sent, self.answers = [], list(answers)

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return json.dumps(self.answers.pop(0)) if isinstance(self.answers[0], dict) else self.answers.pop(0)


rows_json = json.dumps([{"entity_id": "device_tracker.a", "state": "home", "ip": "10.0.0.2", "mac": None, "host_name": None, "keys": ["ip"]}])
ws = FakeWs([{"id": 1, "type": "result", "success": True, "result": None}, {"id": 1, "type": "event", "event": {"result": rows_json, "listeners": {}}}])
got = asyncio.run(ns.fetch_trackers(ws))
assert got[0]["ip"] == "10.0.0.2"
assert [m["type"] for m in ws.sent] == ["render_template"] and ws.sent[0]["template"] == ns.TEMPLATE and ws.sent[0]["timeout"] <= 30
assert "call_service" not in ns.TEMPLATE and "fire_event" not in ns.TEMPLATE
assert "source_type" in ns.TEMPLATE and "router" in ns.TEMPLATE                                    # the filter runs inside Home Assistant: a phone with a position never leaves it
bad = FakeWs([{"id": 1, "type": "result", "success": False, "error": {"code": "template_error", "message": "x"}}])
try:
    asyncio.run(ns.fetch_trackers(bad))
    raise AssertionError("an error from Home Assistant must not pass as an empty answer")
except ns.SurveyError:
    pass
assert ns.parse_template_result("not json") == [] and ns.parse_template_result("{}") == [] and ns.parse_template_result(None) == []     # an odd answer is no list of trackers
assert ns.parse_template_result([{"ip": "1"}, "x"]) == [{"ip": "1"}] and ns.parse_template_result(rows_json)[0]["state"] == "home"       # parsed already, or the text

# --- the switch
assert ns.ENABLED is True
print("TUTTO OK")
