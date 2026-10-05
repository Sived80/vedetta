"""Categoria a punteggio, con i dati reali dei dispositivi di casa (2026-10-04)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import ha_data, roles  # noqa: E402


def port(label, confirmed=True):
    return {"label": label, "confirmed": confirmed}


roles._state.update(by_ip={"192.168.50.1": {"gateway": "route"}, "192.168.50.105": {"repeater": "upnp"}},
                    types={"192.168.50.113": ["MediaRenderer", "Basic", "dial"], "192.168.50.1": ["MediaServer"]})
router = {"ip": "192.168.50.1", "name": "EX233v", "brand": "TP-Link",
          "extra": {"tls_issuer": "commonName=TP-LINK SOHO Router CA/organizationName=EX233v"},
          "scanned_ports": [port("21 · ftp"), port("53 · domain"), port("80 · http"), port("139 · netbios-ssn"),
                            port("445 · microsoft-ds"), port("443 · https"), port("8200 · trivnet1")]}
cases = [
    (router, "router"),                                                        # gateway: ruolo di rete
    ({"ip": "192.168.50.105", "name": "FRITZ!WLAN Repeater 310"}, "router"),   # ripetitore dichiarato
    ({"ip": "192.168.50.113", "name": "SONY XR-55X92K", "extra": {"api_source": "cast"}}, "media"),
    ({"ip": "192.168.50.190", "name": "Milesight", "extra": {"http_server": "webserver"},
      "scanned_ports": [port("80 · Boa httpd"), port("554 · rtsp"), port("8000 · http-alt", False)]}, "media"),
    ({"ip": "192.168.50.199", "name": "IPCAM", "extra": {"onvif_name": "IPCAM", "rtsp_server": "Hipcam RealServer/V1.0"},
      "scanned_ports": [port("80 · Mongoose httpd"), port("554 · Hipcam RealServer rtspd")]}, "media"),
    ({"ip": "192.168.50.103", "name": "Android", "extra": {"mdns_services": "_amzn-wplay._tcp"}}, "media"),
    ({"ip": "192.168.50.201", "name": "Proxmox", "brand": "Proxmox", "scanned_ports": [port("22 · ssh"), port("8006 · pve")]}, "server"),
    ({"ip": "192.168.50.87", "name": "Termostato", "extra": {"api_source": "tasmota"}}, "iot"),
    # la piattaforma (Shelly, Tasmota) dice "apparecchio smart", il nome dice la funzione: vince il nome
    ({"ip": "192.168.50.99", "name": "Cancello", "extra": {"api_source": "shelly"}}, "iot"),
    ({"ip": "192.168.50.98", "name": "Shelly1", "extra": {"api_source": "shelly"}}, "iot"),
    ({"ip": "192.168.50.44", "name": "LED allarme esterno", "extra": {"api_source": "esphome"}}, "iot"),
    # NAS: le porte SMB non lo rendono un PC
    ({"ip": "10.0.0.5", "name": "nas", "brand": "Synology", "scanned_ports": [port("139 · netbios-ssn"), port("445 · microsoft-ds"), port("5001 · https")]}, "server"),
    # PC Windows: desktop remoto verificato
    ({"ip": "10.0.0.6", "name": "ufficio", "scanned_ports": [port("3389 · ms-wbt-server"), port("445 · microsoft-ds")]}, "pc"),
    # Nulla di significativo: resta generico
    ({"ip": "10.0.0.7", "name": "10.0.0.7", "scanned_ports": [port("80 · http", False)]}, "generic"),
]
for device, expected in cases:
    got = ha_data.infer_type(device)
    assert got == expected, (device["name"], expected, got, ha_data.type_scores(device))
# Il router senza ruolo (primi istanti dopo l'avvio) non diventa un PC per le porte SMB.
roles._state.update(by_ip={}, types={})
assert ha_data.infer_type(router) != "pc", ha_data.type_scores(router)
print("TUTTO OK")
