"""Reference test of scan/scan_protocols.py: UPnP blocks grouped by the IP in their Location line, IGMP groups, DHCP offers (only real offers),
NetBIOS / SNMP results of the per-host scripts, and the command lines of the four scans with a fake nmap (bad XML gives an empty answer)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import scan_protocols as sp  # noqa: E402

UPNP = """
  ST: upnp:rootdevice
    Location: http://192.168.1.20:49152/desc.xml
      Name: Living room TV
      Manufacturer: Acme
      Model Name: TV-9000
      Server: Linux/4 UPnP/1.0
      Name: second name ignored
  ST: urn:schemas-upnp-org:device:MediaServer:1
    Location: https://192.168.1.30/root.xml
      Manufacturer: NAS Inc
"""
u = sp._parse_upnp_output(UPNP)
assert u == {"192.168.1.20": {"name": "Living room TV", "manufacturer": "Acme", "model": "TV-9000", "server": "Linux/4 UPnP/1.0"},
             "192.168.1.30": {"manufacturer": "NAS Inc"}}, u
assert sp._parse_upnp_output("Name: before any location\nnothing") == {}

IGMP = """  192.168.1.40
    Group: 239.255.255.250
    Group: 224.0.0.251
  192.168.1.41
    192.168.1.41 other line
  192.168.1.42
    Group: 239.1.1.1
"""
assert sp.parse_igmp(IGMP) == {"192.168.1.40": ["239.255.255.250", "224.0.0.251"], "192.168.1.42": ["239.1.1.1"]}, "a host without groups is dropped"

DHCP = """  Response 1 of 2:
    IP Offered: 192.168.1.77
    DHCP Message Type: DHCPOFFER
    Server Identifier: 192.168.1.1
    Subnet Mask: 255.255.255.0
    Router: 192.168.1.1
    Domain Name Server: 1.1.1.1, 9.9.9.9
    Domain Name: lan
    IP Address Lease Time: 1d00h00m00s
  Response 2 of 2:
    Server Identifier: 192.168.1.2
    DHCP Message Type: DHCPNAK
  Response 3 of 3:
    IP Offered: 192.168.1.78
"""
offers = sp.parse_dhcp_offers(DHCP)
assert len(offers) == 1, "a NAK and an answer without server are not offers"
assert offers[0]["server"] == "192.168.1.1" and offers[0]["dns"] == ["1.1.1.1", "9.9.9.9"] and offers[0]["router"] == ["192.168.1.1"]
assert offers[0]["offered"] == "192.168.1.77" and offers[0]["lease"] == "1d00h00m00s" and offers[0]["domain"] == "lan"
assert sp.parse_dhcp_offers("nothing here") == []

HOST = """<nmaprun><host><status state="up"/><hostscript>
<script id="nbstat" output="NetBIOS name: OFFICE-PC, NetBIOS user: &lt;unknown&gt;, NetBIOS MAC: aa"/>
<script id="snmp-sysdescr" output="  System description: HP LaserJet 400&#10;uptime"/>
<script id="snmp-info" output="  ignored: second description is not used"/>
</hostscript></host></nmaprun>"""
assert sp._parse_protocol_scripts(HOST) == {"netbios_name": "OFFICE-PC", "snmp_descr": "HP LaserJet 400"}, sp._parse_protocol_scripts(HOST)
assert sp._parse_protocol_scripts("<nmaprun/>") == {} and sp._parse_protocol_scripts("garbage") == {}
only_info = HOST.replace('<script id="snmp-sysdescr" output="  System description: HP LaserJet 400&#10;uptime"/>', "")
assert sp._parse_protocol_scripts(only_info)["snmp_descr"] == "ignored: second description is not used", "the first line of the output when there is no 'description:'"

# the four scans with a fake nmap
launched = []
answer = {"xml": ""}


async def fake_nmap(args, semaphore=None):
    launched.append(args)
    return answer["xml"]


sp._run_nmap = fake_nmap
sp.lan_iface = lambda: "eth9"
run = lambda c: asyncio.new_event_loop().run_until_complete(c)   # noqa: E731


def pre(script, output):
    return f'<nmaprun><prescript><script id="{script}" output="{output}"/></prescript></nmaprun>'


answer["xml"] = pre("broadcast-upnp-info", "Location: http://10.0.0.9:80/x&#10;Name: Box")
assert run(sp.ssdp_scan(5)) == {"10.0.0.9": {"name": "Box"}}
assert launched[-1][:5] == ["-sn", "--script", "broadcast-upnp-info", "-e", "eth9"] and "5s" in launched[-1]
answer["xml"] = pre("broadcast-igmp-discovery", "10.0.0.7&#10;Group: 224.0.0.1")
assert run(sp.igmp_scan(7)) == {"10.0.0.7": ["224.0.0.1"]} and "broadcast-igmp-discovery.timeout=7s" in launched[-1] and "11s" in launched[-1]
answer["xml"] = pre("broadcast-dhcp-discover", "Response 1 of 1:&#10;Server Identifier: 10.0.0.1")
assert run(sp.dhcp_discover(8))[0]["server"] == "10.0.0.1" and "16s" in launched[-1]
answer["xml"] = HOST
assert run(sp.protocol_scan("10.0.0.5", 12))["netbios_name"] == "OFFICE-PC"
assert launched[-1][:4] == ["-sU", "-p", "137,161", "-T4"] and launched[-1][-1] == "10.0.0.5" and "12s" in launched[-1]
for bad in ("garbage", "<nmaprun/>"):
    answer["xml"] = bad
    assert run(sp.ssdp_scan()) == {} and run(sp.igmp_scan()) == {} and run(sp.dhcp_discover()) == []
print("TUTTO OK")
