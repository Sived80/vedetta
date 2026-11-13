"""Characterization of the "new devices" alerts as keyed by MAC, before the work on more networks (for a network behind a router there is no MAC, so these alerts are not
used there): observed_macs keeps one entry per MAC (normalized), skips a host without a valid MAC and the skipped addresses, takes the name from DHCP only for a MAC seen now;
list_new shows only the "new" rows whose MAC is present. Fake history; private placeholder addresses.
    python tests/check_newdevices_mac_key.py"""
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import newdevices  # noqa: E402

ARP = {
    "10.0.0.10": {"mac": "aa-bb-cc-00-00-0a", "vendor": None},
    "10.0.0.11": {"mac": "AA:BB:CC:00:00:0B", "vendor": None},
    "10.0.20.30": {"mac": None, "vendor": None},          # a host without MAC (behind a router)
    "10.0.0.12": {"vendor": None},                        # no MAC key at all
    "10.0.0.13": {"mac": "not a mac", "vendor": None},
    "10.0.0.2": {"mac": "02:00:5E:00:00:02", "vendor": None},
}
DHCP = {"AA:BB:CC:00:00:0B": {"hostname": "printer"}, "aa:bb:cc:00:00:99": {"hostname": "gone"}}

seen = newdevices.observed_macs(ARP, DHCP, skip_ips={"10.0.0.2"})
assert set(seen) == {"AA:BB:CC:00:00:0A", "AA:BB:CC:00:00:0B"}, seen
assert seen["AA:BB:CC:00:00:0A"]["ip"] == "10.0.0.10" and seen["AA:BB:CC:00:00:0A"]["hostname"] is None
assert seen["AA:BB:CC:00:00:0B"]["hostname"] == "printer", "the DHCP name goes to a MAC seen now"
assert newdevices.observed_macs({}, DHCP) == {}, "DHCP alone never makes a MAC present"

# one MAC at two addresses: one entry (the last address read wins)
two = newdevices.observed_macs({"10.0.0.10": {"mac": "AA:BB:CC:00:00:0A"}, "10.0.0.20": {"mac": "AA:BB:CC:00:00:0A"}}, {})
assert list(two) == ["AA:BB:CC:00:00:0A"] and two["AA:BB:CC:00:00:0A"]["ip"] == "10.0.0.20", two


class FakeHistory:
    def __init__(self, rows):
        self.rows = rows

    def known_all(self):
        return self.rows


def row(mac, status, ip, first):
    return {"mac": mac, "status": status, "ip": ip, "vendor": None, "hostname": None, "first_seen": first}


hist = FakeHistory({m["mac"]: m for m in (row("AA:BB:CC:00:00:0A", "new", "10.0.0.10", 2.0), row("AA:BB:CC:00:00:0B", "known", "10.0.0.11", 1.0),
                                          row("AA:BB:CC:00:00:0C", "new", "10.0.0.12", 1.0))})
newdevices._present = {"AA:BB:CC:00:00:0A", "AA:BB:CC:00:00:0B"}      # what the last cycle heard (evaluate)
assert [r["mac"] for r in newdevices.list_new(hist)] == ["AA:BB:CC:00:00:0A"], "only the new MACs that are present"
newdevices._present = None
assert [r["mac"] for r in newdevices.list_new(hist)] == ["AA:BB:CC:00:00:0C", "AA:BB:CC:00:00:0A"], "before any search: every new one, oldest first"

print("check_newdevices_mac_key: ok")
