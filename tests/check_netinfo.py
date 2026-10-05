"""Internet (IP pubblico, doppio NAT, CGNAT), interfacce locali, TLS/SSH, conflitti ARP, IGMP."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import internet, localapi, scanner  # noqa: E402

# Risposta DNS con un record A (compressione del nome).
q = internet.build_query(0x2222, "myip.opendns.com")
resp = bytearray(q)
resp[2:4] = b"\x81\x80"
resp[6:8] = struct.pack(">H", 1)
resp += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 0, 4) + bytes([9, 9, 9, 99])
assert internet.parse_a_answer(bytes(resp), 0x2222) == "9.9.9.99"
assert internet.parse_a_answer(bytes(resp), 0x1111) is None

# Percorso reale del 2026-10-04: router e subito un IP pubblico = uscita diretta.
assert internet.classify(["192.168.50.1", "9.9.9.21", "10.40.85.77"]) == {"private_hops": ["192.168.50.1"], "double_nat": False, "cgnat": False}
assert internet.classify(["192.168.50.1", "192.168.1.1", "9.9.9.21"])["double_nat"]
assert internet.classify(["192.168.50.1", "100.70.0.1", "9.9.9.21"])["cgnat"]
X = "<nmaprun><host><trace><hop ttl='2' ipaddr='9.9.9.21'/><hop ttl='1' ipaddr='192.168.50.1'/></trace></host></nmaprun>"
assert internet.parse_trace(X) == ["192.168.50.1", "9.9.9.21"]

# Interfacce locali.
assert localapi.parse_shelly({"type": "SHSW-1", "mac": "AABB", "fw": "1.11"})["api_model"] == "SHSW-1"
assert localapi.parse_shelly({"model": "SNSW-001X16EU", "mac": "AABB", "gen": 2, "fw_id": "2024"})["api_vendor"] == "Shelly"
assert localapi.parse_shelly({"hello": 1}) == {}
r = localapi.parse_tasmota({"Status": {"DeviceName": "Presa", "FriendlyName": ["Presa"]}, "StatusFWR": {"Version": "13.1.0", "Hardware": "ESP8266EX"}, "StatusNET": {"Hostname": "tasmota-1"}})
assert r["api_fw"] == "Tasmota 13.1.0" and r["api_name"] == "Presa" and r["api_model"] == "ESP8266EX", r
r = localapi.parse_roku("<device-info><vendor-name>Roku</vendor-name><model-name>Roku Express</model-name><friendly-device-name>Sala</friendly-device-name></device-info>")
assert r["api_vendor"] == "Roku" and r["api_model"] == "Roku Express", r
assert localapi.parse_sonos("<root><device><manufacturer>Sonos, Inc.</manufacturer><modelName>Sonos One</modelName><friendlyName>Cucina</friendlyName></device></root>")["api_model"] == "Sonos One"
assert localapi.parse_sonos("<root><device><manufacturer>Other</manufacturer></device></root>") == {}

# ESPHome: primo evento del flusso /events (forma reale del dispositivo .44).
ev = ('retry: 30000\nid: 1\nevent: ping\ndata: {"title":"LED allarme esterno","comment":"","ota":true,"uptime":326917}\n\nevent: state\ndata: {}\n')
assert localapi.parse_esphome_events(ev) == {"api_source": "esphome", "api_fw": "ESPHome", "api_name": "LED allarme esterno"}
assert localapi.parse_esphome_events("event: state\ndata: {}\n") == {}

# TLS e SSH.
s, i = scanner.parse_ssl_cert("Subject: commonName=fritz.box/organizationName=AVM\nIssuer: commonName=fritz.box\nPublic Key type: rsa")
assert s == "commonName=fritz.box/organizationName=AVM" and i == "commonName=fritz.box"
assert scanner.parse_ssh_hostkey("\n  3072 SHA256:abc (RSA)\n  256 SHA256:def (ED25519)") == "3072 SHA256:abc (RSA)"

# Conflitti ARP: due MAC sullo stesso IP = conflitto; un MAC su piu' IP (ripetitore) no.
txt = "192.168.1.5\taa:aa:aa:aa:aa:01\tX\n192.168.1.5\taa:aa:aa:aa:aa:02\tY\n192.168.1.9\tbb:bb:bb:bb:bb:01\tZ\n"
hosts = scanner.parse_arp_scan(txt)
assert [h["ip"] for h in hosts] == ["192.168.1.5", "192.168.1.9"]
assert scanner.arp_conflicts == {"192.168.1.5": ["AA:AA:AA:AA:AA:01", "AA:AA:AA:AA:AA:02"]}, scanner.arp_conflicts
txt = "192.168.1.5\tcc:cc:cc:cc:cc:01\t-\n192.168.1.5\tcc:cc:cc:cc:cc:02\t-\n192.168.1.6\tcc:cc:cc:cc:cc:02\t-\n"
scanner.parse_arp_scan(txt)
assert scanner.arp_conflicts == {}, "un MAC che risponde per piu' IP e' un proxy/ripetitore, non un conflitto"

# IGMP.
out = "\n  192.168.1.20\n    Interface: eth0\n    Version: 2\n    Group: 239.255.255.250\n    Description: SSDP\n  192.168.1.21\n    Group: 224.0.0.251\n"
assert scanner.parse_igmp(out) == {"192.168.1.20": ["239.255.255.250"], "192.168.1.21": ["224.0.0.251"]}, scanner.parse_igmp(out)
# Nome dal certificato: solo nomi di rete locale (Proxmox reale: CN=pve.local).
from app import naming  # noqa: E402
assert naming.pick([("tls", naming.cn_host("commonName=pve.local/organizationName=Proxmox Virtual Environment"))]) == ("pve", "tls")
assert naming.cn_host("commonName=*.hiservert.com") is None and naming.cn_host("commonName=tplinkwifi.net") is None
assert naming.pick([("tls", naming.cn_host("commonName=4356345988971635954/organizationName=Google Inc"))]) == (None, None)
# Scansione completa in background: unione delle porte (la voce nuova prevale, le altre restano).
from app import rescan  # noqa: E402
m = rescan._merge_ports([{"label": "80 · http"}, {"label": "12345"}], [{"label": "80 · nginx"}, {"label": "22 · ssh"}])
assert [p["label"] for p in m] == ["22 · ssh", "80 · nginx", "12345"], m
assert 80 in rescan._FAST_SET and 12345 not in rescan._FAST_SET
# Titolo della pagina come fonte debole del nome: solo se sembra un nome.
assert naming.title_name("Termostato - Main Menu") == "Termostato"
assert naming.title_name("Tasmota_gateway_zigbee Main Menu") == "Tasmota_gateway_zigbee"
assert naming.title_name("pve - Proxmox Virtual Environment") == "pve"
for generic in ("Login", "404 Not Found", "Welcome to nginx!", "Index of /", "Dashboard", "", None):
    assert naming.title_name(generic) is None, generic
assert naming.title_name("Login Requested resource was /login.html") is None
assert naming.title_name("Node-RED") == "Node-RED" and naming.title_name("Grafana") == "Grafana"
# istanza di servizio "<id>@<nome>": solo la parte dopo la chiocciola, e solo se e' un nome (4+ lettere)
assert naming.clean_name("AFTMM@ES(192.168.50.103)") is None
assert naming.clean_name("CCCCFE0000B7@SONY XR-55X92K+") == "SONY XR-55X92K+"
assert naming.clean_name("192.168.50.103") is None
assert naming.PRIORITY["web"] < naming.PRIORITY["onvif"] < naming.PRIORITY["tls"] < naming.PRIORITY["nmap"]
print("TUTTO OK")
