"""Golden-master test of scan_protocols.parse_dhcp_offers (text of broadcast-dhcp-discover) and scan_protocols._parse_protocol_scripts (nmap XML with the per-host NetBIOS and SNMP scripts):
3000 generated texts for each - several responses, DHCPNAK and servers missing, lists of routers and DNS, lines before the first response, junk lines; XML that is not valid, without host, with
repeated or empty scripts, SNMP output with and without a "System description" line - must give exactly the results stored in tests/golden/protocols.json, written from the code as it was
before the two functions were split.
Regenerate only on purpose:  PROTOCOLS_GOLDEN_UPDATE=1 python tests/check_protocols_golden.py"""
import json
import os
import random
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_protocols  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "protocols.json"
N = 3000
rng = random.Random(97531)


def pick(seq):
    return seq[rng.randrange(len(seq))]


DHCP_LINES = ["Server Identifier: 192.168.1.1", "Server Identifier: 192.168.1.2", "IP Offered: 192.168.1.50", "Router: 192.168.1.1", "Router: 192.168.1.1, 192.168.1.254",
              "Domain Name Server: 9.9.9.9, 1.1.1.1", "Domain Name Server: 8.8.8.8", "Domain Name: lan", "IP Address Lease Time: 1d00h00m00s", "Subnet Mask: 255.255.255.0",
              "DHCP Message Type: DHCPOFFER", "DHCP Message Type: DHCPNAK", "dhcp message type: dhcpoffer", "  Router:  , ,", "No colon here", "Unknown Key: 5", "Router: a:b",
              "Domain Name Server: "]


def dhcp_text():
    lines = [pick(DHCP_LINES) for _ in range(rng.randrange(0, 3))] if rng.random() < 0.3 else []
    for i in range(rng.randrange(0, 5)):
        lines.append(pick(["Response %d of 2:", "response %d:", "RESPONSE %d of 3"]) % (i + 1))
        body = [pick(["  ", "    |  ", "|_"]) + pick(DHCP_LINES) for _ in range(rng.randrange(0, 7))]
        if rng.random() < 0.75:   # most responses do name their server
            body.insert(rng.randrange(0, len(body) + 1), pick(["  Server Identifier: 192.168.1.1", "  Server Identifier: 10.0.0.1", "|_ Server Identifier: 192.168.1.2"]))
        lines += body
    return "\n".join(lines)


SCRIPT_OUTPUTS = ["NetBIOS name: SALOTTO, NetBIOS user: <unknown>, NetBIOS MAC: aa:bb", "NetBIOS name: " + "N" * 70 + ", x", "NetBIOS name:  PC ,", "no name here", "",
                  "System description: Linux nas 5.10", "sysDescr: Switch 24p", "  \n  first line of text \nsecond", "\n\n", "   ", "Some SNMP info\nmore", "System description:   "]


def xml_text():
    kind = rng.random()
    if kind < 0.08:
        return pick(["", "not xml", "<nmaprun><host>", "<a>"])
    if kind < 0.15:
        return "<nmaprun></nmaprun>"
    scripts = ""
    for _ in range(rng.randrange(0, 6)):
        sid = pick(["nbstat", "nbstat", "snmp-sysdescr", "snmp-info", "other", ""])
        attrs = 'id=%s' % quoteattr(sid)
        if rng.random() < 0.9:
            attrs += ' output=%s' % quoteattr(pick(SCRIPT_OUTPUTS))
        scripts += "<script %s/>" % attrs
    return "<nmaprun><host><hostscript>%s</hostscript></host></nmaprun>" % scripts


out = []
for _ in range(N):
    d, x = dhcp_text(), xml_text()
    row = {"dhcp_in": d, "xml_in": x}
    for name, fn, arg in (("dhcp", scan_protocols.parse_dhcp_offers, d), ("scripts", scan_protocols._parse_protocol_scripts, x)):
        try:
            row[name] = fn(arg)
        except Exception as exc:
            row[name] = {"exception": type(exc).__name__}
    out.append(row)
out = json.loads(json.dumps(out, sort_keys=False))
if os.environ.get("PROTOCOLS_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:500])
assert not any(isinstance(o[k], dict) and "exception" in o[k] for o in out for k in ("dhcp", "scripts"))
offers = sum(len(o["dhcp"]) for o in out)
nb = sum(1 for o in out if "netbios_name" in o["scripts"])
snmp = sum(1 for o in out if "snmp_descr" in o["scripts"])
multi = sum(1 for o in out if len(o["dhcp"]) > 1)
assert offers > 1000 and multi > 200 and nb > 300 and snmp > 300, "scenarios too uniform (%d, %d, %d, %d)" % (offers, multi, nb, snmp)
assert any(isinstance(v, list) for o in out for x in o["dhcp"] for v in x.values())
print("TUTTO OK")
