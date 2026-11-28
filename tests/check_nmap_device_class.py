# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""nmap's own classification of a service is read, not thrown away (1.1.1): the device type nmap names when its service probe matched
(devicetype="switch") gives the group and the finer kind, and the hardware CPE (cpe:/h:<maker>:<model>) names the maker of the device itself.
A MAC maker that also makes boards for others ("dual") counts as the brand when that CPE names the same maker; the CPE maker alone is a
declared brand. Nothing of this needs a brand name in a table: the values are nmap's vocabulary and the device's own answer.
Also: a block of the full background scan (no service detection) does not wipe what a service probe already read on the same port, and a
slow device gets its services read on the open ports it already has, without waiting for the full scan of 65535 ports to end.
All values are invented. Run with tools/run_test.py (it writes a brands.json in the temporary data folder)."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
data_dir = Path(os.environ.get("VEDETTA_DATA_DIR") or sys.exit("run with tools/run_test.py (needs VEDETTA_DATA_DIR)"))
# an invented maker that makes boards for others and finished products: "dual", like the shipped table does for real ones
(data_dir / "brands.json").write_text(json.dumps({"vendor_roles": {"dual": ["examplecorp"]}}), encoding="utf-8")

from app.scan import scan_nmap as nm  # noqa: E402
from app.scan.scan_format import format_scan_info  # noqa: E402
from app.ha.ha_type_evidence import type_scores  # noqa: E402
from app.recognition import brands  # noqa: E402
from app.scan import rescan_background as bg  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


XML = """<?xml version="1.0"?><nmaprun>
<host><status state="up"/><address addr="10.0.0.40" addrtype="ipv4"/><address addr="02:00:00:00:00:40" addrtype="mac" vendor="ExampleCorp"/>
 <ports>
  <port protocol="tcp" portid="80"><state state="open"/>
   <service name="http" product="EXAMPLECORP XS-100 switch httpd" devicetype="switch" method="probed" conf="10">
    <cpe>cpe:/a:examplesoft:webd:2.1</cpe><cpe>cpe:/h:examplecorp:xs-100</cpe></service></port>
  <port protocol="tcp" portid="443"><state state="open"/><service name="https" devicetype="switch" method="table" conf="3"/></port>
  <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH" method="probed"><cpe>cpe:/a:openbsd:openssh</cpe></service></port>
 </ports></host>
<runstats><finished elapsed="1.0"/></runstats></nmaprun>"""

# 1. the parser keeps nmap's device type and the HARDWARE cpe only
host = nm._parse_hosts(XML)[0]
p80, p443, p22 = host["ports"]
check(p80.get("devicetype") == "switch", "the device type nmap names is kept: %r" % p80.get("devicetype"))
check(p80.get("cpe") == "cpe:/h:examplecorp:xs-100", "the hardware CPE is kept, the software one is not: %r" % p80.get("cpe"))
check("cpe" not in p22 and "devicetype" not in p22, "a port with only a software CPE has neither field: %r" % p22)

# 2. they reach the saved card (the same fields scan_format writes for the page and for the background scan)
saved = format_scan_info({"ports": host["ports"]})["ports"]
s80 = next(p for p in saved if p["label"].startswith("80 "))
check(s80.get("devicetype") == "switch" and s80.get("cpe") == "cpe:/h:examplecorp:xs-100", "the saved port keeps both: %r" % s80)
check("devicetype" not in next(p for p in saved if p["label"].startswith("22 ")), "a port without them saves neither")

# 3. the type: a probed match says "network, a switch"; a guess from the port number (method=table) says nothing
kinds: dict = {}
scores = type_scores({"ip": "10.0.0.40", "name": "Device", "scanned_ports": saved}, None, kinds)
check(max(scores, key=scores.get) == "router" and scores["router"] >= 8, "a probed switch is network equipment: %r" % scores)
check(max(kinds, key=kinds.get, default=None) == "netswitch", "and its finer kind is the network switch: %r" % kinds)
guess = [{"label": "443 · https", "confirmed": False, "category": "web", "devicetype": "switch"}]
check(type_scores({"ip": "10.0.0.41", "name": "Device", "scanned_ports": guess}).get("router", 0) == 0, "a device type on a port nmap did not probe gives no points")
two = saved + [{"label": "8080 · http", "confirmed": True, "category": "web", "devicetype": "switch"}]
check(type_scores({"ip": "10.0.0.40", "name": "Device", "scanned_ports": two}).get("router") == scores.get("router"), "two ports with the same device type count once")

# 4. the brand: a dual MAC maker is the brand when the device's own hardware CPE names the same maker
hw = ["cpe:/h:examplecorp:xs-100"]
web = "EXAMPLECORP XS-100 switch httpd"
check(brands.vendor_role("ExampleCorp") == "dual", "the invented maker is dual (brands.json of the test)")
check(brands.resolve("ExampleCorp", names=[], web_text=web)["brand"] is None, "a dual MAC maker alone is still no brand (as before)")
both = brands.resolve("ExampleCorp", names=[], web_text=web, hardware=hw)
check(both["brand"] == "ExampleCorp" and both["confidence"] == "high", "MAC maker and hardware CPE agree: the brand, high: %r" % both)
alone = brands.resolve("Chipmaker", names=[], web_text=web, hardware=hw)
check(alone["brand"] and alone["brand"].lower() == "examplecorp" and alone["confidence"] == "medium" and alone["source"] == "declared",
      "the hardware CPE alone is a declared brand, written as the device writes it: %r" % alone)
check(brands.resolve(None, names=[], hardware=["cpe:/a:examplesoft:webd"])["brand"] is None, "a software CPE says nothing of the brand")

# 5. a bare block of the background scan does not overwrite what the service probe read on the same port
bare = [{"label": "80 · http", "confirmed": False, "category": "web"}]
merged = bg.merge_ports(saved, bare)
check(next(p for p in merged if p["label"].startswith("80 ")) == s80, "the probed entry of port 80 survives a bare block: %r" % merged)
check(bg.merge_ports(bare, [s80]) == [s80], "a probed entry still replaces a bare one")

# 6. a slow device has its services read on the ports it already has, before the full scan ends
check(bg.services_due({"ports": bare}) is True, "open ports, never read: due")
check(bg.services_due({"ports": bare, "services_at": 1.0}) is False, "already read: not again until the full scan ends")
check(bg.services_due({"ports": [{"label": "9100", "confirmed": False, "category": "print"}]}) is False, "only a no-talk port: nothing to read")
check(bg.services_due({}) is False, "no port: nothing to read")

# 7. the calm deep search of a slow device (no service detection) keeps what the service probe read on a port it sees open again;
# a port it no longer sees is not brought back
from app.scan import rescan  # noqa: E402
previous = {"slow_scan": True, "services_at": 1.0, "ports": [s80, {"label": "443 · https", "confirmed": True, "category": "web"}]}
fields = {"ports": [{"label": "80 · http", "confirmed": False, "category": "web"}]}
rescan._keep_ports_of_slow_device(fields, {"slow_scan": True}, {"scan_info": previous})
check([p.get("cpe") for p in fields["ports"]] == ["cpe:/h:examplecorp:xs-100"], "the probed port 80 stays as it was read, 443 (closed now) is not kept: %r" % fields["ports"])

print("FAILED: %d" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
