"""Reference (characterisation) test of DeviceState.poll_once, the whole check cycle, with the network faked.

It pins down the order and the data flow of 0.6.2 without judging it: the configuration is read, every device is probed together with the
shared ARP view, latency is measured for all, each result goes to _apply with its own latency sample, a failed probe is skipped (the others
still go through), a device that left the configuration is removed, and then the post-steps run in a fixed order (latency saved, IP changes
followed with the ARP view, phones merged, IP conflicts reported, new devices checked with the same ARP view) before `ready` is set."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import state as state_mod, state_cycle  # noqa: E402
from app.scan import latency, probe  # noqa: E402
from app.storage import devices_config  # noqa: E402

CONFIGS = [{"id": "a", "ip": "10.0.0.1", "port": 80}, {"id": "b", "ip": "10.0.0.2"}, {"id": "c", "ip": "10.0.0.3", "port": 443}]
ARP = {"10.0.0.1": {"mac": "aa:bb:cc:00:00:01"}}
log = []

devices_config.load_devices = lambda: list(CONFIGS)
state_mod.update_generic_titles = lambda configs: log.append(("titles", len(configs)))
state_cycle.update_generic_titles = state_mod.update_generic_titles


async def fake_probe(config, arp_task):
    arp = await arp_task                       # the shared ARP view is the same awaitable for every device
    log.append(("probe", config["id"], config.get("last_mac"), arp is ARP))
    if config["id"] == "b":
        raise RuntimeError("probe broke")
    return {"id": config["id"], "online": True}


async def fake_measure_many(targets):
    log.append(("latency", targets))
    return {"a": 12.0, "c": 34.0}


probe.probe_device = fake_probe
latency.measure_many = fake_measure_many

st = state_mod.DeviceState()
st._last_mac["a"] = "aa:bb:cc:00:00:01"
st.devices["gone"] = {"id": "gone"}           # a card whose device left the configuration


async def fake_arp(max_age):
    log.append(("arp", max_age))
    return ARP


async def rec(name, *a):
    log.append((name,) + a)

st._arp_by_ip = fake_arp
st._apply = lambda config, result, current, sample=None, force=False: log.append(("apply", config["id"], result["id"], sample, sorted(current)))
st.remove = lambda device_id: log.append(("remove", device_id))
st._save_latency = lambda: rec("save_latency")
st.follow_ip_changes = lambda arp: rec("follow", arp is ARP)
st.merge_duplicate_phones = lambda: rec("merge")
st.report_ip_conflicts = lambda: log.append(("conflicts",))
st.check_new_devices = lambda arp: rec("new_devices", arp is ARP)
st._record_macs = lambda arp: rec("record_macs", arp is ARP)

asyncio.new_event_loop().run_until_complete(st.poll_once())

kinds = [e[0] for e in log]
assert kinds[0] == "titles" and log[0] == ("titles", 3)
probes = {e[1]: e for e in log if e[0] == "probe"}
assert set(probes) == {"a", "b", "c"} and all(p[3] for p in probes.values()), "every device is probed on the same ARP view"
assert probes["a"][2] == "aa:bb:cc:00:00:01" and probes["c"][2] is None, "the last known MAC travels with the config"
assert ("arp", 0) in log, "the cycle asks for a fresh ARP view (max age 0)"
assert ("latency", [("a", "10.0.0.1", 80), ("b", "10.0.0.2", 80), ("c", "10.0.0.3", 443)]) in log, "port defaults to 80"
applied = [e for e in log if e[0] == "apply"]
assert applied == [("apply", "a", "a", 12.0, ["a", "b", "c"]), ("apply", "c", "c", 34.0, ["a", "b", "c"])], applied
assert ("remove", "gone") in log and ("remove", "b") not in log
tail = kinds[kinds.index("remove"):]
assert tail == ["remove", "save_latency", "follow", "merge", "conflicts", "new_devices", "record_macs"], tail
assert ("follow", True) in log and ("new_devices", True) in log and ("record_macs", True) in log
assert st.ready.is_set()
print("TUTTO OK")
