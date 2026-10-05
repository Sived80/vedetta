"""Ruoli di rete e client dietro un ripetitore (dati reali del test del 2026-10-04)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import dhcp, discovery, roles  # noqa: E402

UPNP = {
    "192.168.50.1": {"types": ["MediaServer"], "name": "EX233v", "model": "Windows Media Connect compatible (MiniDLNA)"},
    "192.168.50.105": {"types": ["fritzbox"], "name": "FRITZ!WLAN Repeater 310", "model": "FRITZ!WLAN Repeater 310"},
    "192.168.50.113": {"types": ["MediaRenderer", "Basic", "dial"], "name": "SONY XR-55X92K"},
}
ARP = {"192.168.50.1": {"mac": "b0:19:21:00:00:a9"}, "192.168.50.105": {"mac": "4e:3a:fd:00:00:a5"},
       "192.168.50.112": {"mac": "4E-3A-FD-00-00-A5".replace("-", ":")}, "192.168.50.91": {"mac": "4e:3a:fd:00:00:a5"},
       "192.168.50.113": {"mac": "38:b8:00:00:00:a8"}}
r = roles.compute(gateway="192.168.50.1", dhcp_servers=["192.168.50.1"], dns_servers=["192.168.50.2"], upnp=UPNP, arp=ARP)
assert r["by_ip"]["192.168.50.1"] == {"gateway": "route", "dhcp": "dhcp"}, r
assert r["by_ip"]["192.168.50.2"] == {"dns": "dns"}
assert r["by_ip"]["192.168.50.105"] == {"repeater": "upnp"}
assert "192.168.50.113" not in r["by_ip"]  # un TV non e' un apparato di rete
assert r["via"]["192.168.50.112"] == {"ip": "192.168.50.105", "name": "FRITZ!WLAN Repeater 310", "mac": "4E:3A:FD:00:00:A5"}, r["via"]
assert set(r["via"]) == {"192.168.50.112", "192.168.50.91"}
# MAC condiviso senza nessuno che si dichiari ripetitore: proprietario non identificato.
r = roles.compute(gateway=None, dhcp_servers=[], dns_servers=[], upnp={}, arp=ARP)
assert r["via"]["192.168.50.105"]["ip"] is None and len(r["via"]) == 3
# Tipi UPnP di rete.
r = roles.compute(gateway=None, dhcp_servers=[], dns_servers=[], arp={},
                  upnp={"10.0.0.1": {"types": ["InternetGatewayDevice", "WANDevice", "WFADevice"], "name": "Box"}})
assert r["by_ip"]["10.0.0.1"] == {"router": "upnp", "ap": "upnp"}, r
# Descrittore UPnP con dispositivi annidati.
x = ("<root><device><deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType><friendlyName>Box</friendlyName>"
     "<manufacturer>ACME</manufacturer><modelName>R1</modelName><deviceList><device>"
     "<deviceType>urn:schemas-upnp-org:device:WANDevice:1</deviceType></device></deviceList></device></root>")
assert discovery.parse_description(x) == {"types": ["InternetGatewayDevice", "WANDevice"], "name": "Box", "manufacturer": "ACME", "model": "R1"}
# DHCP: opzione 54 di una REQUEST.
pkt = bytearray(240)
pkt[0] = 1
pkt[28:34] = bytes.fromhex("aabbccddeeff")
pkt[236:240] = bytes([99, 130, 83, 99])
pkt += bytes([53, 1, 3, 54, 4, 192, 168, 50, 1, 12, 3]) + b"abc" + bytes([255])
mac, info = dhcp.parse(bytes(pkt))
assert mac == "aa:bb:cc:dd:ee:ff" and info["server_id"] == "192.168.50.1" and info["hostname"] == "abc", info
# Query DNS standard: intestazione (id, RD), una domanda A/IN per example.com.
q = roles._dns_query(0x1234)
assert q[:4] == bytes([0x12, 0x34, 0x01, 0x00]) and q[12:25] == bytes([7]) + b"example" + bytes([3]) + b"com" + bytes([0]), q
assert q[-4:] == bytes([0, 1, 0, 1])
# Offerte DHCP (testo reale di broadcast-dhcp-discover, formato nmap).
from app import scanner  # noqa: E402
OUT = """
  Response 1 of 1:
    Interface: eth0
    IP Offered: 192.168.50.120
    DHCP Message Type: DHCPOFFER
    Server Identifier: 192.168.50.1
    IP Address Lease Time: 1d00h00m00s
    Subnet Mask: 255.255.255.0
    Router: 192.168.50.1
    Domain Name Server: 192.168.50.2
    Domain Name: lan
"""
offers = scanner.parse_dhcp_offers(OUT)
assert offers == [{"offered": "192.168.50.120", "type": "DHCPOFFER", "server": "192.168.50.1", "lease": "1d00h00m00s",
                   "netmask": "255.255.255.0", "router": ["192.168.50.1"], "dns": ["192.168.50.2"], "domain": "lan"}], offers
r = roles.compute(gateway="192.168.50.1", dhcp_servers=[], dns_servers=[], upnp={}, arp={}, offers=offers)
assert r["by_ip"]["192.168.50.1"] == {"gateway": "route", "dhcp": "offer"}, r
assert r["by_ip"]["192.168.50.2"] == {"dns": "offer"}, r
assert r["dhcp"] == [{"server": "192.168.50.1", "router": ["192.168.50.1"], "dns": ["192.168.50.2"], "domain": "lan",
                      "lease": "1d00h00m00s", "netmask": "255.255.255.0"}], r["dhcp"]
# Due server: due voci.
two = scanner.parse_dhcp_offers(OUT + OUT.replace("Response 1 of 1", "Response 2 of 2").replace("Server Identifier: 192.168.50.1", "Server Identifier: 192.168.50.66"))
assert sorted(o["server"] for o in two) == ["192.168.50.1", "192.168.50.66"]
print("TUTTO OK")
